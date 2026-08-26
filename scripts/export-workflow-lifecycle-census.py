#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Export an immutable Actions run/job census snapshot (issue #527, Wave 1).

This is the SOLE networked step in the verification-launch baseline pipeline and
is explicit-invocation-only: it is never run by the offline analyzer. It queries
the GitHub Actions API (via gh) for ONE declared repository, workflow set, and
closed time window, paginates, and writes an immutable metadata-only snapshot
(run/job identity, run ID + attempt, created/started/completed timestamps,
conclusion). The offline analyzer (verification_baseline.py) reads this snapshot
without any network access.

Scope: only each run's LATEST attempt is censused (the runs list endpoint returns
one row per run at its latest attempt); superseded re-run attempts are out of
Wave-1 scope and recorded as ``attempt_coverage: "latest_only"`` rather than left
as a silent under-count.

The snapshot records its hash, query time, and pagination completeness. It
contains ONLY Actions metadata — no transcript text, no tool input, no stdout/
stderr, no secrets, no source paths. An absent or incomplete snapshot makes the
analyzer's cloud coverage ``unavailable``, never zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = 1
FILE_MODE = 0o600
DIR_MODE = 0o700


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _usable_run_id(run_id: object) -> bool:
    """A run id usable as a jobs_by_run dict key.

    `bool` is EXCLUDED even though it is an int subclass: True == 1 and
    False == 0 hash identically, so a shape-drifted `"id": true` row would pass a
    bare isinstance(run_id, (int, str)) check and then silently OVERWRITE the
    jobs of a genuine run whose id is 1 — misattributing jobs between two runs
    rather than being counted as malformed. Shape drift is this file's declared
    threat model, so a boolean id sits inside it (PR #531 review-and-fix,
    iteration-4 fix-delta gate). Shared by both call sites so the two cannot
    drift apart.
    """
    return isinstance(run_id, (int, str)) and not isinstance(run_id, bool)


def build_snapshot(repo: str, workflow_set: list[str], closed_after: str, closed_before: str,
                   runs: list[dict[str, Any]], jobs_by_run: dict[int, list[dict[str, Any]]],
                   query_time: str, pagination_complete: bool) -> dict[str, Any]:
    """Build the immutable census snapshot from already-fetched runs + jobs.

    Pure function (no network) — testable independently of gh. ``rows`` carries
    ONLY Actions metadata: workflow/job identity, run ID + attempt, timestamps,
    conclusion, status, html_url. No transcript text, no secrets, no source paths.
    """
    rows: list[dict[str, Any]] = []
    dropped_runs = 0
    dropped_jobs = 0
    for run in runs:
        if not isinstance(run, dict):
            # A corrupt/API-shifted run never vanishes from the census silently:
            # count it so a shape drift does not shrink the denominator while the
            # snapshot self-certifies complete (PR #531 early-shadow — the
            # analyzer's sibling reader already counts malformed rows; the
            # producer must too).
            dropped_runs += 1
            continue
        run_id = run.get("id")
        if not _usable_run_id(run_id):
            # Covers `id` absent (None), non-scalar, AND boolean (see the helper). A
            # non-scalar id is unhashable, and it is used as a dict key
            # (jobs_by_run) — so an API shape drift there raised TypeError out of
            # fetch_runs_and_jobs and killed the whole export with no snapshot
            # written at all, meaning the "incomplete snapshot reads unavailable,
            # never zero" contract never got the chance to apply. That is the
            # same failure class the non-dict guard above closed one branch over;
            # this file's declared threat model IS shape drift, so a non-scalar
            # id sits inside it. Count it as malformed like any other drifted
            # row (PR #531 review-and-fix, convergence shadow).
            dropped_runs += 1
            continue
        wf_path = run.get("path") or run.get("workflow_file")
        wf_name = run.get("name")
        # Unknown stays unknown (never collapsed onto the real value 1): an
        # absent run_attempt is recorded as null so a reader of the immutable
        # snapshot can distinguish "attempt 1" from "attempt unestablished"
        # (the repo's unknown-is-not-zero discipline; PR #531 early-shadow).
        attempt = run.get("run_attempt")
        for job in jobs_by_run.get(run_id, []):
            if not isinstance(job, dict):
                dropped_jobs += 1
                continue
            rows.append({
                "workflow_file": wf_path,
                "workflow_name": wf_name,
                "job": job.get("name"),
                "run_id": run_id,
                "run_attempt": attempt,
                "created_at": run.get("created_at"),
                # started_at is the JOB-level start ONLY (null when the agent step
                # never started) — the analyzer's cloud-eligibility guard reads it
                # as per-job evidence, so folding in the run-level start would make
                # every job of a started run look started (issue #527 review). The
                # run-level start is carried separately for reference.
                "started_at": job.get("started_at"),
                "run_started_at": run.get("run_started_at"),
                "completed_at": job.get("completed_at"),
                # conclusion/status are JOB-level ONLY (null when the jobs API
                # omits them) — the analyzer's eligibility guard reads them as
                # per-job evidence, so folding in the run-level values would
                # promote a job with no job-level evidence to
                # confirmed_eligible on the run's say-so: the same fail-open
                # the started_at/run_started_at split above closes (PR #531
                # iteration-1; the run-level values are carried separately for
                # reference, exactly like run_started_at).
                "conclusion": job.get("conclusion"),
                "status": job.get("status"),
                "run_conclusion": run.get("conclusion"),
                "run_status": run.get("status"),
                "html_url": job.get("html_url") or run.get("html_url"),
            })
    if dropped_runs or dropped_jobs:
        print(
            f"devflow census-export: dropped {dropped_runs} malformed/id-less run(s) "
            f"and {dropped_jobs} malformed job(s) from the census",
            file=sys.stderr,
        )
    rows_payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot_hash = hashlib.sha256(rows_payload).hexdigest()
    # A malformed run/job dropped from the census means the row set is not a
    # complete view of the queried window: fold it into pagination_complete so the
    # analyzer reads the snapshot as unavailable rather than a clean partial
    # (PR #531 early-shadow: a corrupt API shape silently shrank the denominator
    # while the snapshot still self-certified complete).
    complete = bool(pagination_complete) and dropped_runs == 0 and dropped_jobs == 0
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "snapshot_hash": snapshot_hash,
        "query_time": query_time,
        "pagination_complete": complete,
        "dropped_run_count": dropped_runs,
        "dropped_job_count": dropped_jobs,
        "repository": repo,
        "workflow_set": workflow_set,
        "closed_window": {"created_after": closed_after, "created_before": closed_before},
        # The runs list endpoint returns only each run's LATEST attempt, and this
        # exporter does not enumerate prior attempts — so superseded re-run
        # attempts are not in the census. Record that scope explicitly as a durable,
        # visible fact rather than leaving it a silent under-count (issue #527 review).
        "attempt_coverage": "latest_only",
        "row_count": len(rows),
        "rows": rows,
    }


def _gh_json(gh: str, args: list[str]) -> Any:
    """Run gh with --jq '.' (JSON) and parse. Returns None on failure.

    Surfaces gh's stderr on a non-zero exit so the sole networked step is
    diagnosable: a 401, a rate limit, and a legitimately empty window no longer
    all read as an indistinguishable "pagination_complete=False"."""
    cmd = [gh, *args, "--jq", "."]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    except FileNotFoundError as exc:
        # gh not found / not on PATH / broken DEVFLOW_GH override. Name it, like the
        # rc-nonzero and malformed-stdout branches below (issue #527 review) — else
        # a missing gh is an indistinguishable, reasonless "pagination incomplete".
        print(f"devflow census-export: gh not found ({exc}); set DEVFLOW_GH or install gh — treating as a failed fetch", file=sys.stderr)
        return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"devflow census-export: gh invocation failed ({type(exc).__name__}: {exc}); treating as a failed fetch", file=sys.stderr)
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        stderr = (proc.stderr or "").strip()
        # Breadcrumb UNCONDITIONALLY: an rc!=0 with empty stderr, and an rc==0
        # with empty stdout, previously degraded with no diagnostic at all —
        # the indistinguishable reasonless pagination_complete=False this
        # function's docstring says was fixed (PR #531 iteration-1,
        # silent-failure finding 4). Name the rc and whether stdout was empty.
        print(
            f"devflow census-export: gh failed (rc={proc.returncode}, stdout "
            f"{'empty' if not proc.stdout.strip() else 'present'})"
            + (f": {stderr[:300]}" if stderr else " — no stderr from gh"),
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        # A gh success with malformed stdout degrades to None (→ pagination
        # incomplete). Surface it like the rc-nonzero branch above so it isn't a
        # silent failure indistinguishable from an empty window (issue #527 review).
        print("devflow census-export: gh returned malformed JSON stdout; treating as a failed fetch", file=sys.stderr)
        return None


def fetch_runs_and_jobs(gh: str, repo: str, workflows: list[str], created_after: str, created_before: str) -> tuple[list[dict], dict[int, list[dict]], bool]:
    """Paginate Actions runs + their jobs via gh. Returns (runs, jobs_by_run, pagination_complete).

    Pagination is complete only if every page was fetched and the final page was
    a partial page (< per_page); a transport failure on any page marks it
    incomplete (the analyzer then reads cloud coverage as unavailable, never zero).
    """
    runs: list[dict] = []
    fetched_runs = 0  # unfiltered count actually returned by the API, for the total_count cross-check
    page = 1
    per_page = 100
    pagination_complete = True
    while True:
        # --method GET is REQUIRED: `gh api` switches to POST as soon as any
        # parameter is added, and POSTing to the GET-only runs endpoint fails
        # (returns None here) — so without it the exporter can never fetch a run.
        # The closed window is ONE `created` range param (`after..before`): a
        # separate `created<=` field is split by gh on the first `=` into the
        # unknown key `created<`, which GitHub ignores, silently dropping the
        # upper bound (issue #527 review findings). `--raw-field` forces the
        # value to a string, avoiding `--field`'s magic type coercion.
        doc = _gh_json(gh, ["api", "--method", "GET", f"repos/{repo}/actions/runs",
                            f"--field=per_page={per_page}", f"--field=page={page}",
                            f"--raw-field=created={created_after}..{created_before}"])
        if doc is None or not isinstance(doc, dict):
            pagination_complete = False
            break
        page_runs = doc.get("workflow_runs")
        if not isinstance(page_runs, list):
            pagination_complete = False
            break
        # Filter to the declared workflow set by workflow path/name. A NON-DICT
        # row is deliberately KEPT here rather than filtered out: build_snapshot
        # already owns the malformed-row contract (it counts the row into
        # dropped_runs and folds that into pagination_complete=False), so
        # discarding it at fetch time made that guard UNREACHABLE — dropped_runs
        # stayed 0 and the snapshot self-certified complete over a silently
        # shrunk denominator, the exact fail-open the guard exists to close
        # (PR #531 review-and-fix iter-1, code-reviewer Critical). Share the
        # consumer's own contract instead of re-deriving a second counting path
        # here; `_matches_workflow_set` is only asked about real dicts.
        filtered = [r for r in page_runs
                    if not isinstance(r, dict) or _matches_workflow_set(r, workflows)] if workflows else list(page_runs)
        runs.extend(filtered)
        fetched_runs += len(page_runs)
        if len(page_runs) < per_page:
            # Last (partial) page. Cross-check total_count the SAME way the jobs
            # loop below does (the sibling guard this PR added): if the API
            # reported more runs than we actually fetched, an intermediate short
            # or transiently-empty page ended the loop early — mark incomplete
            # rather than trust a partial run set presented as a complete window
            # (PR #531 shadow, silent-failure-hunter: the runs loop had only the
            # short-page heuristic while the jobs loop cross-checked total_count).
            # When the runs endpoint omits total_count (or returns it non-int) the
            # check is inapplicable, so fall back to the short-page heuristic and
            # leave a breadcrumb that completeness could not be cross-checked.
            total = doc.get("total_count")
            # `bool` is an `int` subclass in Python, so a shape-drifted
            # `total_count: true` would read as 1 and fail OPEN (mark a genuinely
            # undercounted window complete) — exclude it so the missing-operand
            # breadcrumb arm handles it instead (#62/#98 operand-contract shape).
            if isinstance(total, int) and not isinstance(total, bool):
                if fetched_runs < total:
                    pagination_complete = False
            else:
                print("devflow census-export: runs endpoint reported no usable total_count; "
                      "run-pagination completeness rests on the short-page heuristic alone",
                      file=sys.stderr)
            break
        page += 1
        if page > 200:  # hard cap; a real closed window is bounded
            pagination_complete = False
            break
    jobs_by_run: dict[int, list[dict]] = {}
    for run in runs:
        if not isinstance(run, dict):
            # A malformed row now reaches here (it is kept above so
            # build_snapshot can count it). It has no jobs to fetch and must not
            # be asked for `.get` — the unguarded call raised AttributeError and
            # took down the whole export, so the "incomplete snapshot reads
            # unavailable, never zero" contract never got the chance to apply
            # (PR #531 review-and-fix iter-1, code-reviewer Critical).
            continue
        run_id = run.get("id")
        if not _usable_run_id(run_id):
            # A non-scalar id is UNHASHABLE and this loop uses it as a
            # jobs_by_run key, so the bare `is None` check let a shape-drifted
            # row raise TypeError here and take down the whole export before any
            # snapshot could be written. Skipping fetches no jobs for it; the row
            # still reaches build_snapshot, whose matching guard counts it into
            # dropped_runs and folds that into pagination_complete=False — the
            # analyzer then reads the census as unavailable rather than the
            # export dying (PR #531 review-and-fix, convergence shadow).
            continue
        # Page the jobs endpoint the SAME way as runs — a run with a large matrix
        # can have >100 jobs, and a single per_page=100 fetch silently truncated
        # the cloud denominator while still reporting pagination_complete=True
        # (issue #527 review finding). A transport failure or a page that under-
        # counts vs total_count marks the census incomplete (the analyzer then
        # reads cloud coverage as unavailable, never a partial-presented-as-whole).
        collected: list[dict] = []
        jpage = 1
        truncated = False
        while True:
            jdoc = _gh_json(gh, ["api", "--method", "GET", f"repos/{repo}/actions/runs/{run_id}/jobs",
                                 f"--field=per_page={per_page}", f"--field=page={jpage}"])
            if jdoc is None or not isinstance(jdoc, dict) or not isinstance(jdoc.get("jobs"), list):
                truncated = True
                break
            page_jobs = jdoc["jobs"]
            collected.extend(page_jobs)
            total = jdoc.get("total_count")
            if len(page_jobs) < per_page:
                # Last (partial) page. If the API told us a total and we have
                # fewer, something was dropped — mark incomplete rather than trust
                # a short census. When the jobs endpoint omits total_count (or
                # returns it non-int) the completeness check is INAPPLICABLE, so
                # leave a breadcrumb rather than fail open silently on the
                # missing-operand shape (PR #531 shadow, silent-failure-hunter:
                # job truncation was undetectable — and unremarked — without a
                # usable total_count).
                if isinstance(total, int) and not isinstance(total, bool):
                    if len(collected) < total:
                        truncated = True
                else:
                    print(f"devflow census-export: jobs endpoint for run {run_id} reported no "
                          "usable total_count; job-pagination completeness rests on the short-page "
                          "heuristic alone", file=sys.stderr)
                break
            jpage += 1
            if jpage > 200:  # hard cap; a real run's job count is bounded
                truncated = True
                break
        if truncated:
            pagination_complete = False
        jobs_by_run[run_id] = collected
    return runs, jobs_by_run, pagination_complete


def _matches_workflow_set(run: dict, workflows) -> bool:
    # Reads the SAME field set build_snapshot resolves (path OR workflow_file,
    # plus name): checking only path/name silently excluded from a --workflows
    # filter a run the snapshot side would have accepted via the workflow_file
    # alternate — a quiet denominator shrink with pagination_complete=True
    # (PR #531 early-shadow, silent-failure finding 5).
    path = run.get("path") or run.get("workflow_file") or ""
    name = run.get("name") or ""
    return any(wf in (path, name) for wf in workflows)


def _atomic_write(path: Path, data: bytes) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent, DIR_MODE)
    except OSError as exc:
        # Same class-sweep fix as the analyzer's _atomic_write (PR #531
        # iteration-1): a failed hardening chmod stays best-effort but is
        # surfaced, never silent.
        print(f"devflow census-export: could not chmod {parent} to 0700 ({exc}); artifacts may carry umask permissions", file=sys.stderr)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".census-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp) and tmp != str(path):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _iso_window_bound(value: str) -> str:
    """Validate a --created-after/--created-before bound is ISO-8601-shaped.

    GitHub silently ignores a malformed `created` range filter, so an
    unvalidated bound would make the snapshot self-record a closed_window it
    does not actually have (PR #531 early-shadow). Shape check only (the API
    accepts date or datetime forms); a malformed bound is a loud argparse
    error, never a silently-open window."""
    from datetime import datetime as _dt
    try:
        _dt.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 timestamp/date: {value!r}") from exc
    return value


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description="Export an immutable Actions run/job census snapshot (issue #527).")
    parser.add_argument("--repo", required=True, help="owner/repo to census")
    parser.add_argument("--workflows", default="", help="comma-separated workflow file paths/names to include (empty = all)")
    parser.add_argument("--created-after", required=True, type=_iso_window_bound, help="ISO-8601; runs created at or after")
    parser.add_argument("--created-before", required=True, type=_iso_window_bound, help="ISO-8601; runs created at or before (inclusive upper bound of the closed window)")
    parser.add_argument("--out", required=True, help="output snapshot path")
    parser.add_argument("--gh", default=os.environ.get("DEVFLOW_GH") or "gh")
    args = parser.parse_args(argv)

    workflows = [w.strip() for w in args.workflows.split(",") if w.strip()] if args.workflows else []
    query_time = _now_iso()
    runs, jobs_by_run, pagination_complete = fetch_runs_and_jobs(args.gh, args.repo, workflows, args.created_after, args.created_before)
    if workflows and not runs and pagination_complete:
        # A non-empty --workflows filter matched zero runs in a fully-fetched
        # window: almost certainly a typo'd path/name (an empty census then reads
        # as a genuine agent-less window). Surface it rather than let it pass as a
        # real empty window (issue #527 review, loud degradation).
        print(f"devflow census-export: WARNING — --workflows {workflows} matched 0 of the fetched runs; check the workflow path/name (the census will be empty)", file=sys.stderr)
    snapshot = build_snapshot(args.repo, workflows, args.created_after, args.created_before, runs, jobs_by_run, query_time, pagination_complete)
    payload = json.dumps(snapshot, indent=2, sort_keys=True).encode("utf-8")
    # Deliberate asymmetry with the analyzer (PR #531 review, LOW): --out is NOT
    # routed through the analyzer's _validate_admitted_path — the exporter is
    # explicit-invocation-only, its output path is operator-typed (not
    # attacker-shaped transcript data), and writing the snapshot outside the
    # repo root is a legitimate use.
    out_path = Path(args.out)
    _atomic_write(out_path, payload)
    # Report the RECORDED value, not the fetch-level local. build_snapshot folds
    # dropped rows into the flag it writes (`complete = pagination_complete and
    # dropped_runs == 0 and dropped_jobs == 0`), so a dropped-row census made
    # this line print `pagination_complete=True` while the artifact it had just
    # written said false — stdout contradicting its own file — AND took the
    # `if not pagination_complete` branch as false, so the degradation the
    # comment below calls "the operator must see it" was silent on exactly the
    # path that needed it. Reading the snapshot keeps the reported value and the
    # durable record the same operand by construction, rather than two
    # derivations that can disagree (PR #531 review-and-fix iter-1, shadow).
    recorded_complete = snapshot["pagination_complete"]
    print(f"devflow census-export: wrote {out_path} (rows={snapshot['row_count']} pagination_complete={recorded_complete} hash={snapshot['snapshot_hash'][:12]})")
    if not recorded_complete:
        # Loud degradation: the snapshot is INCOMPLETE (a transport failure, a
        # truncated page, or a dropped malformed row). The analyzer reads this as
        # cloud coverage 'unavailable' (never a partial-as-complete census), so
        # exit 0 is intentional — the degraded snapshot is still usable — but the
        # operator must see it (issue #527 review). The in-file
        # `pagination_complete: false` is the durable record. Name WHICH cause
        # fired: the counts are already on the snapshot, and "pagination
        # incomplete" alone misdiagnoses a clean-transport dropped-row census.
        print(
            "devflow census-export: WARNING — snapshot incomplete (transport failure, truncated page, "
            f"or {snapshot['dropped_run_count']} dropped run(s) / {snapshot['dropped_job_count']} dropped job(s)); "
            "the snapshot is partial and the analyzer will read cloud coverage as unavailable",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

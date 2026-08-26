#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Report where an implement run's wall-clock went, from its execution transcript.

    implement-timeline.py --run-id <id> [--json <path>] [--repo <owner/repo>]
    implement-timeline.py --transcript <path> [--json <path>]

`--run-id` downloads the run's scrubbed execution-transcript artifact (uploaded by the
cloud workflows behind `prflow.execution_transcript_artifact_enabled`, 7-day retention).
An artifact that has expired or was never uploaded prints a notice naming the expiry and
exits 0 — an absent artifact is a normal outcome for a run older than the retention
window, not a failure of this tool.

Three views over the same walk:
  per-phase     — attributed tool-call time grouped by the implement phase file in force
  per-step      — every tool call in order, with its phase, tool name and duration
  per-activity  — attributed tool-call time grouped by tool name, across all phases

Phase attribution changes only on a `Read` whose `file_path` matches an
`skills/implement/phases/<name>.md` path IN FULL. A bare `phase-N` match would attribute
the review engine's own `skills/review/phases/*.md` files — which an implement run reads
throughout Phase 3 — to an implement phase that was never entered.

The transcript is input this repository does not itself produce, so every malformed shape
is answered rather than assumed: an empty artifact, a truncated final record, a record
that parses to a non-object, a `tool_use` whose `tool_result` never arrives (a denied
call), a record with no timestamp, and a decreasing timestamp pair. A duration that
cannot be established is the string `unestablished` and is excluded from every total —
never `0`, which is a real duration a fast call genuinely produces.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_eval_shared import UNESTABLISHED  # noqa: E402
from workflow_flight_recorder import _timestamp_ms  # noqa: E402

# The directory whose phase files mark an implement phase boundary. The trailing slash is
# load-bearing: without it `skills/implement/phases` would also prefix-match a sibling
# directory added later, and with a bare `phase-` match the review engine's own phase
# files would be attributed to implement phases they never belonged to.
PHASE_PREFIX = "skills/implement/phases/"
UNATTRIBUTED = "unattributed"

# How many per-step rows the TEXT channel renders; a real implement transcript runs to
# thousands of tool calls, and --json always carries every one.
PER_STEP_RENDER_CAP = 200


class ArtifactExpired(Exception):
    """The run's transcript artifact is gone — expired past retention, or never uploaded."""


# `gh run download`'s observed stderr for a REAL run holding no matching artifact,
# reproduced against this repository: `no valid artifacts found to download`. Matching a
# bare `not found` instead would also swallow the HTTP 404 a NONEXISTENT run id returns,
# reporting "your artifact expired" for a run that never existed.
_EXPIRED_MARKERS = (
    "no valid artifacts found to download",
    "no artifacts found",
    "no artifact matching",
)
# The observed stderr for a nonexistent run id, reproduced against this repository:
# `error fetching artifacts: HTTP 404: Not Found (https://api.github.com/repos/…)`.
_RUN_MISSING_MARKERS = ("http 404",)


def _classify_download_failure(stderr: str) -> str:
    """`expired` | `run-missing` | `other` for one `gh run download` failure.

    Kept separate from the subprocess call so the discrimination is drivable by a test
    without stubbing a process, and so an arm names the condition it observed.
    """
    low = (stderr or "").lower()
    for marker in _EXPIRED_MARKERS:
        if marker in low:
            return "expired"
    for marker in _RUN_MISSING_MARKERS:
        if marker in low:
            return "run-missing"
    return "other"


def _artifact_name_prefix(run_id: str) -> str:
    """The uploaders name the artifact `<prefix>-<run_attempt>`, so this is a PREFIX and
    never a whole name — `gh run download -n` matches exactly, and handing it the
    attempt-less form misses every artifact there is."""
    return f"claude-execution-transcript-{run_id}-"


def resolve_artifact_name(run_id: str, listing):
    """The full artifact name for `run_id` from a run's artifact listing, or None.

    Selects the HIGHEST attempt numerically: a re-run uploads a further artifact under the
    same run id, and the latest attempt is the one whose transcript describes the run a
    caller asking for that id means. Anchored on the trailing `-` so run 7712's artifact is
    never admitted for run 77.
    """
    prefix = _artifact_name_prefix(run_id)
    best, best_attempt = None, None
    for item in listing or []:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        if not suffix.isdigit():
            continue
        attempt = int(suffix)
        if best_attempt is None or attempt > best_attempt:
            best, best_attempt = name, attempt
    return best


def _list_run_artifacts(gh, run_id, repo):
    """The run's artifact listing. Raises RuntimeError when it could not be established.

    Paginated: a run with more artifacts than one page would otherwise resolve to no match
    and be reported as an expired artifact, which is success-shaped.
    """
    slug = repo if repo else "{owner}/{repo}"
    cmd = [gh, "api", "--paginate",
           f"repos/{slug}/actions/runs/{run_id}/artifacts", "--jq", ".artifacts[]"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"could not run {gh}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if _classify_download_failure(detail) == "run-missing":
            raise RuntimeError(f"run {run_id} was not found in this repository: {detail}")
        raise RuntimeError(f"gh api artifacts failed (rc {proc.returncode}): {detail}")
    items = []
    for line in (proc.stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"could not parse the artifact listing for run {run_id}: {exc}") from exc
    return items


def download_transcript(run_id: str, dest: Path, repo: str | None = None) -> Path:
    """Download the run's scrubbed transcript artifact into `dest`, returning its path.

    Raises ArtifactExpired when `gh` reports no matching artifact — the shape a run past
    the 7-day retention window produces, and equally the shape of a run whose upload was
    gated off.
    """
    # The documented override wins verbatim and is never probed — matching every other
    # Python gh caller and lib/resolve-gh.sh. A `which` probe would pick the present-but-
    # unrunnable Windows/WSL shim the override exists to route around.
    gh = os.environ.get("DEVFLOW_GH") or "gh"
    # Resolve the artifact's FULL name first — `-n` matches exactly, and the uploaders
    # append the run attempt — then download that name.
    name = resolve_artifact_name(run_id, _list_run_artifacts(gh, run_id, repo))
    if name is None:
        raise ArtifactExpired(
            f"no artifact named {_artifact_name_prefix(run_id)}<attempt> on run {run_id} "
            f"(expired past the 7-day retention, or never uploaded)")
    cmd = [gh, "run", "download", str(run_id), "-D", str(dest)]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(["-n", name])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"could not run {gh}: {exc}") from exc
    detail = (proc.stderr or proc.stdout or "").strip()
    # Classify only a FAILURE. Classifying first read a successful download whose output
    # merely mentioned a marker phrase as an expired artifact.
    if proc.returncode != 0:
        kind = _classify_download_failure(detail)
        if kind == "expired":
            raise ArtifactExpired(detail)
        if kind == "run-missing":
            raise RuntimeError(f"run {run_id} was not found in this repository: {detail}")
        raise RuntimeError(f"gh run download failed (rc {proc.returncode}): {detail}")
    files = sorted(p for p in dest.rglob("*") if p.is_file())
    if not files:
        # gh reports the no-matching-artifact case on stdout at exit 0, so an empty
        # download directory is that same expired condition rather than a new one — this
        # is what still catches it now that classification is gated on a non-zero status.
        raise ArtifactExpired(f"artifact {name} downloaded no files: {detail}")
    return files[0]


def _iter_records(raw: str):
    """(record, skipped_count) over a JSONL stream, tolerating unparseable lines.

    Deliberately not `workflow_flight_recorder.parse_events`, which raises on the first
    malformed line and on an empty stream: a truncated final record and an empty artifact
    are both expected inputs here, and a raise would lose the whole run's timeline over
    one bad trailing byte.
    """
    skipped = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue
        yield record, skipped
    yield None, skipped



def _tool_items(record):
    """(tool_use items, tool_result items) from one transcript record, in ONE pass.

    Resolves the message/content shape once, in this function: a second copy of that rule
    drifts from this one the moment the transcript shape changes.
    Deliberately not `workflow_flight_recorder._content`, which returns no tool_results
    and joins every text block into a string this caller discards — a wasted allocation
    per record over a transcript that runs to tens of megabytes.
    """
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    uses, results = [], []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use":
                uses.append(item)
            elif item.get("type") == "tool_result":
                results.append(item)
    return uses, results


def _phase_from_read(item) -> str | None:
    """The implement phase a tool_use enters, or None when it enters none."""
    if item.get("name") != "Read":
        return None
    inp = item.get("input")
    if not isinstance(inp, dict):
        return None
    path = inp.get("file_path")
    if not isinstance(path, str):
        return None
    # Strip a vendored or absolute prefix so a consumer checkout and a cloud runner
    # resolve to the same plugin-relative form.
    idx = path.find(PHASE_PREFIX)
    if idx < 0:
        return None
    return path[idx:]


def read_transcript(path):
    """`(text, note)` for one transcript file. Undecodable bytes are named as their own
    cause rather than replaced and then re-reported as unparseable records — those are
    different failures, and only one of them means the artifact is not a transcript."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return data.decode("utf-8", errors="replace"), (
            f"the artifact holds undecodable bytes at offset {exc.start} and is probably "
            f"not a UTF-8 transcript; the records below are what survived replacement")


def build_timeline(raw: str, notes=None) -> dict:
    """The three views over one transcript. Never raises on a malformed transcript."""
    starts: dict[str, tuple[int | None, str, str]] = {}
    order: list[str] = []
    finishes: dict[str, int | None] = {}
    skipped = 0
    current = UNATTRIBUTED

    for record, skipped in _iter_records(raw):
        if record is None:
            break
        ts = _timestamp_ms(record.get("timestamp")) if isinstance(record.get("timestamp"), str) else None
        tool_uses, tool_results = _tool_items(record)
        for item in tool_uses:
            tool_id = item.get("id")
            if not isinstance(tool_id, str) or tool_id in starts:
                continue
            name = item.get("name") if isinstance(item.get("name"), str) else "unknown"
            # Enter the phase BEFORE attributing this call, so the Read that opens a
            # phase is charged to the phase it opens rather than to the one it leaves —
            # entering a phase is part of that phase's cost, and charging it backwards
            # would credit every phase with its successor's entry.
            entered = _phase_from_read(item)
            if entered is not None:
                current = entered
            starts[tool_id] = (ts, name, current)
            order.append(tool_id)
        for item in tool_results:
            rid = item.get("tool_use_id")
            if isinstance(rid, str) and rid in starts and rid not in finishes:
                finishes[rid] = ts

    steps = []
    phases: dict[str, int] = {}
    activities: dict[str, int] = {}
    for tool_id in order:
        start_ms, name, phase = starts[tool_id]
        end_ms = finishes.get(tool_id)
        # A denied call never returns a tool_result, and a record with no timestamp or a
        # backwards pair yields no span. Each is unknown, never a zero-millisecond call.
        if start_ms is None or end_ms is None or end_ms < start_ms:
            duration = UNESTABLISHED
        else:
            duration = end_ms - start_ms
        steps.append({"tool_use_id": tool_id, "tool": name, "phase": phase,
                      "duration_ms": duration})
        if duration == UNESTABLISHED:
            continue
        phases[phase] = phases.get(phase, 0) + duration
        activities[name] = activities.get(name, 0) + duration

    diagnostics = list(notes or [])
    if not raw.strip():
        # An empty or whitespace-only artifact renders identically to a run that made no
        # tool calls, so say which it was.
        diagnostics.append("the artifact holds no records at all — it is empty or "
                           "whitespace-only, which is not the same as a run that made no "
                           "tool calls")
    if skipped:
        diagnostics.append(
            f"skipped {skipped} unparseable record(s) — a truncated final line, or a "
            f"record that is not a JSON object")
    return {"phases": phases, "steps": steps, "activities": activities,
            "diagnostics": diagnostics}


def _render(timeline: dict) -> str:
    out = []
    out.append("Per-phase wall clock")
    for phase, ms in sorted(timeline["phases"].items(), key=lambda kv: -kv[1]):
        out.append(f"  {ms / 1000:9.1f}s  {phase}")
    out.append("")
    out.append("Per-activity wall clock")
    for tool, ms in sorted(timeline["activities"].items(), key=lambda kv: -kv[1]):
        out.append(f"  {ms / 1000:9.1f}s  {tool}")
    out.append("")
    steps = timeline["steps"]
    shown = steps if len(steps) <= PER_STEP_RENDER_CAP else steps[:PER_STEP_RENDER_CAP]
    out.append(f"Per-step wall clock ({len(steps)} step(s), in order"
               + (f"; showing the first {PER_STEP_RENDER_CAP} — pass --json for all)"
                  if len(shown) < len(steps) else ")"))
    for index, step in enumerate(shown, start=1):
        duration = step["duration_ms"]
        rendered = (UNESTABLISHED if duration == UNESTABLISHED
                    else f"{duration / 1000:.1f}s")
        phase = step["phase"]
        label = phase if phase == UNATTRIBUTED else Path(phase).name
        out.append(f"  {index:>4}  {rendered:>12}  {step['tool']:<10}  {label}")
    unestablished = sum(1 for s in timeline["steps"] if s["duration_ms"] == UNESTABLISHED)
    if unestablished:
        out.append(f"  {unestablished} step(s) have an unestablished duration "
                   f"(a denied call, a missing timestamp, or a backwards pair) and are "
                   f"excluded from every total above")
    for line in timeline["diagnostics"]:
        out.append(f"  note: {line}")
    return "\n".join(out)


def main(argv=None, _download=download_transcript):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--run-id", help="workflow run id whose transcript artifact to read")
    src.add_argument("--transcript", help="a transcript file already on disk")
    parser.add_argument("--json", dest="json_path",
                        help="also write the same data as JSON to this path")
    parser.add_argument("--repo", help="owner/repo, when not inferable from the git remote")
    args = parser.parse_args(argv)

    notes = []
    if args.transcript:
        try:
            raw, note = read_transcript(args.transcript)
        except OSError as exc:
            print(f"devflow: implement-timeline: cannot read {args.transcript}: {exc}",
                  file=sys.stderr)
            return 1
        if note:
            notes.append(note)
    else:
        with tempfile.TemporaryDirectory() as td:
            try:
                path = _download(args.run_id, Path(td), args.repo)
            except ArtifactExpired as exc:
                print(f"Notice: the execution-transcript artifact for run {args.run_id} "
                      f"has expired or is unavailable (7-day retention): {exc}")
                return 0
            except RuntimeError as exc:
                print(f"devflow: implement-timeline: {exc}", file=sys.stderr)
                return 1
            try:
                raw, note = read_transcript(path)
            except OSError as exc:
                # The same failure class the --transcript arm names; the temp directory is
                # gone by the time a traceback would surface, so name it here too.
                print(f"devflow: implement-timeline: cannot read the downloaded artifact "
                      f"for run {args.run_id}: {exc}", file=sys.stderr)
                return 1
            if note:
                notes.append(note)

    timeline = build_timeline(raw, notes)
    print(_render(timeline))
    if args.json_path:
        try:
            Path(args.json_path).write_text(
                json.dumps(timeline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"devflow: implement-timeline: cannot write {args.json_path}: {exc}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

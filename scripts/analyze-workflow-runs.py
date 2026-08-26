#!/usr/bin/env python3
"""Analyze captured PRFlow workflow occurrences with a fresh read-only model."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
REPORT_BEGIN = "<!-- DEVFLOW_REPORT_BEGIN -->"
REPORT_END = "<!-- DEVFLOW_REPORT_END -->"
ISSUE_BEGIN = re.compile(
    r"^<!-- DEVFLOW_ISSUE_BEGIN slug=([a-z0-9][a-z0-9-]{0,62}) runs=([A-Za-z0-9._,-]+) -->$",
    re.MULTILINE,
)
ISSUE_END = "<!-- DEVFLOW_ISSUE_END -->"


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


class AnalysisError(Exception):
    """A safe, user-facing analyzer failure."""


@dataclass(frozen=True)
class SessionBundle:
    path: Path
    session_id: str
    captured_at: dt.datetime
    metadata: dict[str, Any]
    occurrences: tuple[dict[str, Any], ...]
    provenance: str
    event_summary: dict[str, Any]
    event_summary_status: str


@dataclass(frozen=True)
class SelectedOccurrence:
    bundle: SessionBundle
    occurrence: dict[str, Any]

    @property
    def session_id(self) -> str:
        return self.bundle.session_id

    @property
    def occurrence_id(self) -> str:
        return str(self.occurrence["occurrence_id"])

    @property
    def workflow(self) -> str:
        return str(self.occurrence["workflow"])

    @property
    def mode(self) -> str:
        return str(self.occurrence["mode"])


def git_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AnalysisError("current directory is not inside a Git repository") from exc
    return Path(result.stdout.strip()).resolve()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"{path.parent.name!r} has invalid {path.name}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"{path.parent.name!r} has non-object {path.name}")
    return value


def _captured(metadata: dict[str, Any], bundle: Path) -> dt.datetime:
    value = metadata.get("captured_at")
    if not isinstance(value, str):
        raise AnalysisError(f"bundle {bundle.name!r} has no captured_at timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnalysisError(f"bundle {bundle.name!r} has invalid captured_at timestamp") from exc
    if parsed.tzinfo is None:
        raise AnalysisError(f"bundle {bundle.name!r} captured_at has no timezone")
    return parsed


def _validate_identity(bundle: Path, metadata: dict[str, Any]) -> None:
    if not SAFE_ID.fullmatch(bundle.name) or metadata.get("session_id") != bundle.name:
        raise AnalysisError(f"bundle {bundle.name!r} metadata identity does not match")
    if not (bundle / "transcript.jsonl").is_file():
        raise AnalysisError(f"bundle {bundle.name!r} has no transcript.jsonl")


def load_session_bundle(path: Path) -> SessionBundle:
    metadata = _json_object(path / "metadata.json")
    _validate_identity(path, metadata)
    try:
        occurrences = json.loads((path / "occurrences.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"bundle {path.name!r} has invalid occurrences.json") from exc
    if not isinstance(occurrences, list) or not occurrences:
        raise AnalysisError(f"bundle {path.name!r} has no workflow occurrences")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in occurrences:
        if not isinstance(item, dict):
            raise AnalysisError(f"bundle {path.name!r} has a non-object occurrence")
        occurrence_id = item.get("occurrence_id")
        if not isinstance(occurrence_id, str) or not SAFE_ID.fullmatch(occurrence_id) or occurrence_id in seen:
            raise AnalysisError(f"bundle {path.name!r} has an unsafe or duplicate occurrence id")
        if not isinstance(item.get("workflow"), str) or not SAFE_ID.fullmatch(item["workflow"]):
            raise AnalysisError(f"bundle {path.name!r} has an unsafe workflow id")
        if item.get("mode") not in {"top-level", "nested"}:
            raise AnalysisError(f"bundle {path.name!r} has an invalid occurrence mode")
        seen.add(occurrence_id)
        normalized.append(dict(item))
    # An absent event-summary.json is a bundle that never captured one; a present but
    # unreadable one is corrupted evidence. Both degrade to {}, so record which it was
    # rather than letting the analyst read "unavailable" over a corrupted file.
    event_summary: dict[str, Any] = {}
    event_summary_status = "absent"
    if (path / "event-summary.json").exists():
        try:
            event_summary = _json_object(path / "event-summary.json")
            event_summary_status = "present"
        except AnalysisError as exc:
            event_summary_status = "corrupted"
            print(f"devflow: workflow-run-analysis: {exc}", file=sys.stderr)
    return SessionBundle(
        path=path, session_id=path.name, captured_at=_captured(metadata, path),
        metadata=metadata, occurrences=tuple(normalized), provenance="workflow_bundle",
        event_summary=event_summary, event_summary_status=event_summary_status,
    )


def load_legacy_implement_bundle(path: Path) -> SessionBundle:
    """Normalize a legacy bundle in memory without changing its files."""
    metadata = _json_object(path / "metadata.json")
    _validate_identity(path, metadata)
    occurrence = {
        "occurrence_id": "implement-1",
        "workflow": "implement",
        "mode": "top-level",
        "parent_occurrence_id": None,
        "subject": {"kind": "issue", "number": metadata.get("issue_number")},
        "invocation_source": "legacy_bundle",
        "start_event": 0,
        "started_at": None,
        "start_timestamp_source": None,
        "boundary_confidence": "unknown",
        "preceding_context_events": 0,
        "prompt_fingerprint": metadata.get("prompt_fingerprint"),
        "observed_models": [],
        "observed_effort": [],
    }
    return SessionBundle(
        path=path, session_id=path.name, captured_at=_captured(metadata, path),
        metadata=metadata, occurrences=(occurrence,), provenance="legacy_implement_bundle",
        event_summary={}, event_summary_status="absent",
    )


def _discover(root: Path) -> list[SessionBundle]:
    found: dict[str, SessionBundle] = {}
    locations = (
        (root / ".prflow/tmp/workflow-runs", load_session_bundle),
        (root / ".prflow/tmp/implement-runs", load_legacy_implement_bundle),
    )
    for bundle_root, loader in locations:
        if not bundle_root.is_dir():
            continue
        for path in bundle_root.iterdir():
            if not path.is_dir() or not SAFE_ID.fullmatch(path.name) or path.name in found:
                continue
            try:
                found[path.name] = loader(path)
            except AnalysisError as exc:
                # A bundle that fails to load is dropped from selection, so say so:
                # silently shrinking the cohort makes vanished evidence indistinguishable
                # from evidence that was never captured.
                print(
                    f"devflow: workflow-run-analysis: skipping unusable bundle: {exc}",
                    file=sys.stderr,
                )
                continue
    return sorted(found.values(), key=lambda item: item.captured_at, reverse=True)


def _parse_selection_args(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--last", type=int)
    parser.add_argument("--workflow")
    parser.add_argument("--mode", choices=("top-level", "nested", "all"), default="all")
    parser.add_argument("selectors", nargs="*")
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exc:
        raise AnalysisError("invalid analyzer arguments") from exc
    if args.last is not None and args.last < 1:
        raise AnalysisError("--last requires a positive count")
    if args.last is not None and args.selectors and args.selectors != ["latest"]:
        raise AnalysisError("--last cannot be combined with explicit session ids")
    if not args.selectors:
        args.selectors = ["latest"]
    return args


def select_occurrences(arguments: list[str], repository_root: Path) -> list[SelectedOccurrence]:
    args = _parse_selection_args(arguments)
    available = _discover(repository_root)
    candidates: list[SelectedOccurrence] = []
    for bundle in available:
        for occurrence in bundle.occurrences:
            if args.workflow and occurrence.get("workflow") != args.workflow:
                continue
            if args.mode != "all" and occurrence.get("mode") != args.mode:
                continue
            candidates.append(SelectedOccurrence(bundle, occurrence))
    candidates.sort(
        key=lambda item: (item.bundle.captured_at, int(item.occurrence.get("start_event", 0))), reverse=True
    )
    if args.selectors == ["latest"]:
        count = args.last if args.last is not None else 1
        session_ids: list[str] = []
        for item in candidates:
            if item.session_id not in session_ids:
                session_ids.append(item.session_id)
            if len(session_ids) == count:
                break
        if len(session_ids) != count:
            raise AnalysisError(f"requested {count} session(s), but only {len(session_ids)} are available")
        return [item for item in candidates if item.session_id in session_ids]

    requested: list[tuple[str, str | None]] = []
    for selector in args.selectors:
        session_id, separator, occurrence_id = selector.partition(":")
        if not SAFE_ID.fullmatch(session_id) or (separator and not SAFE_ID.fullmatch(occurrence_id)):
            raise AnalysisError(f"unsafe session id or occurrence selector: {selector!r}")
        requested.append((session_id, occurrence_id if separator else None))
    selected = [
        item for item in candidates
        if any(
            item.session_id == session_id and (occurrence_id is None or item.occurrence_id == occurrence_id)
            for session_id, occurrence_id in requested
        )
    ]
    for session_id, occurrence_id in requested:
        if not any(
            item.session_id == session_id and (occurrence_id is None or item.occurrence_id == occurrence_id)
            for item in selected
        ):
            raise AnalysisError(f"selected occurrence not found: {session_id}{':' + occurrence_id if occurrence_id else ''}")
    return selected


def _fact_values(selected: list[SelectedOccurrence], occurrence_key: str, summary_key: str) -> set[str]:
    values: set[str] = set()
    for item in selected:
        observed = item.occurrence.get(occurrence_key)
        if not isinstance(observed, list) or not observed:
            observed = item.bundle.event_summary.get("model_effort", {}).get(summary_key, [])
        if isinstance(observed, list):
            values.update(value for value in observed if isinstance(value, str) and value)
    return values


def recurrence_eligibility(selected: list[SelectedOccurrence]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], set[str]] = {}
    for item in selected:
        fingerprint = item.occurrence.get("prompt_fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            groups.setdefault((item.workflow, item.mode, fingerprint), set()).add(item.session_id)
    eligible_groups = [sorted(sessions) for sessions in groups.values() if len(sessions) >= 2]
    confounders: list[str] = []
    fingerprints = {item.occurrence.get("prompt_fingerprint") for item in selected}
    if len(fingerprints) > 1 or None in fingerprints:
        confounders.append("prompt_fingerprint")
    if len(_fact_values(selected, "observed_models", "observed_models")) > 1:
        confounders.append("model")
    if len(_fact_values(selected, "observed_effort", "observed_effort")) > 1:
        confounders.append("effort")
    modes = {item.mode for item in selected}
    if len(modes) > 1:
        confounders.append("invocation_mode")
    return {
        "eligible": bool(eligible_groups),
        "supporting_session_ids": sorted({item.session_id for item in selected}),
        "eligible_groups": eligible_groups,
        "confounders": confounders,
        "rule": "unique sessions with same workflow, mode, and non-null prompt fingerprint",
    }


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _analysis_dir(root: Path, selected: list[SelectedOccurrence]) -> Path:
    identities = ",".join(f"{item.session_id}:{item.occurrence_id}" for item in selected)
    digest = hashlib.sha256(identities.encode()).hexdigest()[:10]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / ".prflow/tmp/workflow-analyses" / f"{stamp}-{digest}"


def parse_output(
    output: str, cohort_session_ids: list[str], eligibility: dict[str, Any]
) -> tuple[str, list[tuple[str, str]]]:
    if output.count(REPORT_BEGIN) != 1 or output.count(REPORT_END) != 1:
        raise AnalysisError("model output must contain exactly one report block")
    begin = output.index(REPORT_BEGIN) + len(REPORT_BEGIN)
    end = output.index(REPORT_END)
    if end < begin:
        raise AnalysisError("report delimiters are out of order")
    report = output[begin:end].strip()
    if not report:
        raise AnalysisError("report block is empty")
    headers = list(ISSUE_BEGIN.finditer(output))
    if output.count("<!-- DEVFLOW_ISSUE_BEGIN") != len(headers) or output.count(ISSUE_END) != len(headers):
        raise AnalysisError("issue delimiters are malformed or unbalanced")
    unique_sessions = set(cohort_session_ids)
    if len(unique_sessions) == 1 and headers:
        raise AnalysisError("single-session analysis cannot publish issue drafts")
    if headers and not eligibility.get("eligible"):
        raise AnalysisError("issue drafts require mode- and fingerprint-stratified recurrence")
    eligible_groups = [set(group) for group in eligibility.get("eligible_groups", [])]
    issues: list[tuple[str, str]] = []
    seen_slugs: set[str] = set()
    cursor = 0
    for header in headers:
        close = output.find(ISSUE_END, header.end())
        next_header = output.find("<!-- DEVFLOW_ISSUE_BEGIN", header.end())
        if header.start() < cursor or close < 0 or (next_header >= 0 and next_header < close):
            raise AnalysisError("issue blocks overlap, nest, or are unclosed")
        slug = header.group(1)
        if not SAFE_SLUG.fullmatch(slug) or slug in seen_slugs:
            raise AnalysisError("issue slug is unsafe or duplicated")
        supporting = header.group(2).split(",")
        support_set = set(supporting)
        if len(supporting) != len(support_set) or len(support_set) < 2:
            raise AnalysisError(f"issue {slug!r} needs two unique supporting sessions")
        if not support_set.issubset(unique_sessions) or not any(support_set.issubset(group) for group in eligible_groups):
            raise AnalysisError(f"issue {slug!r} cites sessions without eligible recurrence")
        body = output[header.end():close].strip()
        if not body:
            raise AnalysisError(f"issue {slug!r} is empty")
        issues.append((slug, body))
        seen_slugs.add(slug)
        cursor = close + len(ISSUE_END)
    return report, issues


def _cohort_document(selected: list[SelectedOccurrence], eligibility: dict[str, Any]) -> dict[str, Any]:
    def model_effort(item: SelectedOccurrence) -> dict[str, Any]:
        summary = item.bundle.event_summary.get("model_effort", {})
        summary = summary if isinstance(summary, dict) else {}
        observed_models = item.occurrence.get("observed_models")
        used_session_fallback = False
        if not isinstance(observed_models, list) or not observed_models:
            observed_models = summary.get("observed_models", [])
            used_session_fallback = True
        observed_effort = item.occurrence.get("observed_effort")
        if not isinstance(observed_effort, list) or not observed_effort:
            observed_effort = summary.get("observed_effort", [])
            used_session_fallback = True
        return {
            "requested_model": summary.get("requested_model"),
            "requested_model_source": summary.get("requested_model_source"),
            "requested_effort": summary.get("requested_effort"),
            "requested_effort_source": summary.get("requested_effort_source"),
            "observed_models": observed_models,
            "observed_effort": observed_effort,
            "observed_source": (
                "session_summary_fallback"
                if used_session_fallback
                else item.occurrence.get("model_effort_source")
            ),
            "observed_event_count": (
                None if used_session_fallback else item.occurrence.get("model_effort_event_count")
            ),
        }

    return {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_ids": sorted({item.session_id for item in selected}),
        "occurrences": [
            {
                "session_id": item.session_id, "occurrence_id": item.occurrence_id,
                "workflow": item.workflow, "mode": item.mode,
                "prompt_fingerprint": item.occurrence.get("prompt_fingerprint"),
                "provenance": item.bundle.provenance,
                "event_summary_status": item.bundle.event_summary_status,
                "model_effort": model_effort(item),
            }
            for item in selected
        ],
        "recurrence": eligibility,
    }


def _prompt(selected: list[SelectedOccurrence], eligibility: dict[str, Any]) -> str:
    prompt_path = Path(__file__).parent / "prompts/workflow-flight-recorder-analysis.md"
    if not prompt_path.is_file():
        prompt_path = Path(__file__).parent / "prompts/implement-flight-recorder-analysis.md"
    template = prompt_path.read_text(encoding="utf-8")
    supplied = _cohort_document(selected, eligibility)
    supplied["bundle_paths"] = sorted({str(item.bundle.path.resolve()) for item in selected})
    return f"{template}\n\nSelected local evidence (JSON):\n{json.dumps(supplied, indent=2, sort_keys=True)}\n"


def _split_repository_root(argv: list[str]) -> tuple[Path, list[str]]:
    if "--repository-root" not in argv:
        return git_root(), argv
    index = argv.index("--repository-root")
    if index + 1 >= len(argv):
        raise AnalysisError("--repository-root requires a path")
    root = Path(argv[index + 1]).resolve()
    return root, argv[:index] + argv[index + 2:]


DEFAULT_ANALYST_TIMEOUT_SECONDS = 900.0


def _analyst_timeout() -> float:
    """Seconds to wait for the analyst before giving up, overridable and fail-soft."""
    raw = os.environ.get("DEVFLOW_CLAUDE_TIMEOUT")
    if not raw:
        return DEFAULT_ANALYST_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value <= 0 or value != value or value == float("inf"):
        print(
            f"devflow: workflow-run-analysis: DEVFLOW_CLAUDE_TIMEOUT value {raw!r} is not a "
            f"positive number of seconds; using default {DEFAULT_ANALYST_TIMEOUT_SECONDS:.0f}s",
            file=sys.stderr,
        )
        return DEFAULT_ANALYST_TIMEOUT_SECONDS
    return value


def main(argv: list[str]) -> int:
    _force_utf8_streams()
    try:
        acknowledgement = "--acknowledge-provider-access"
        if acknowledgement not in argv:
            raise AnalysisError(
                "analysis may send selected transcript evidence to the configured provider; "
                "review the privacy scope and pass --acknowledge-provider-access"
            )
        argv = [argument for argument in argv if argument != acknowledgement]
        root, selection_args = _split_repository_root(argv)
        selected = select_occurrences(selection_args, root)
        eligibility = recurrence_eligibility(selected)
        unique_sessions = sorted({item.session_id for item in selected})
        out_dir = _analysis_dir(root, selected)
        if len(unique_sessions) > 1:
            atomic_text(out_dir / "cohort.json", json.dumps(
                _cohort_document(selected, eligibility), indent=2, sort_keys=True
            ))
        command = [
            os.environ.get("DEVFLOW_CLAUDE_BIN", "claude"),
            "--safe-mode", "--print", "--permission-mode", "dontAsk",
            "--allowedTools", "Read,Grep,Glob", _prompt(selected, eligibility),
        ]
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=_analyst_timeout(),
            )
        except subprocess.TimeoutExpired as exc:
            raise AnalysisError(
                f"analyst did not respond within {exc.timeout:.0f}s; "
                "raise DEVFLOW_CLAUDE_TIMEOUT to allow longer runs"
            ) from exc
        if result.returncode != 0:
            diagnostic = result.stderr or f"model exited {result.returncode}"
            atomic_text(out_dir / "model-error.txt", diagnostic)
            raise AnalysisError(f"analyst failed; diagnostic: {out_dir / 'model-error.txt'}")
        try:
            report, issues = parse_output(result.stdout, unique_sessions, eligibility)
        except AnalysisError:
            atomic_text(out_dir / "invalid-model-output.txt", result.stdout)
            if result.stderr:
                atomic_text(out_dir / "model-stderr.txt", result.stderr)
            raise
        if len(unique_sessions) == 1:
            destination = selected[0].bundle.path / "run-report.md"
            atomic_text(destination, report)
            print(destination)
        else:
            destination = out_dir / "comparison-report.md"
            atomic_text(destination, report)
            for slug, body in issues:
                atomic_text(out_dir / "issue-drafts" / f"{slug}.md", body)
            print(out_dir)
        return 0
    except (AnalysisError, OSError) as exc:
        print(f"devflow: workflow-run-analysis: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

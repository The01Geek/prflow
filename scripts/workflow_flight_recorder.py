#!/usr/bin/env python3
"""Pure parsing and capture primitives for local PRFlow workflow sessions."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

# The closed set of values each field may hold. analyze-workflow-runs.py re-validates
# OccurrenceMode when reading a bundle back, since a bundle on disk is untrusted input.
OccurrenceMode = Literal["top-level", "nested"]
BoundaryConfidence = Literal["unknown", "exact", "approximate"]

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
COMMAND_MARKUP = re.compile(
    r"<command-message>\s*(?P<command>/?[A-Za-z0-9:_-]+)\s*</command-message>"
    r"[\s\S]*?<command-args>\s*(?P<args>[\s\S]*?)\s*</command-args>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SurfaceDefinition:
    glob: str
    load_class: str
    required: bool


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow: str
    user_commands: tuple[str, ...]
    skill_aliases: tuple[str, ...]
    subject_kind: str
    argument_pattern: re.Pattern[str] | None
    allowed_parents: tuple[str, ...]
    surfaces: tuple[SurfaceDefinition, ...]


@dataclass(frozen=True)
class Event:
    index: int
    raw: dict[str, Any]
    timestamp: str | None
    timestamp_ms: int | None
    role: str | None
    text: str
    tool_uses: tuple[dict[str, Any], ...]


@dataclass
class Occurrence:
    # Deliberately mutable, unlike every sibling here: boundary resolution discovers an
    # occurrence's end, timing, and model/effort facts across three later passes over the
    # event stream, and rebuilding a frozen instance per pass would buy immutability at
    # the cost of the correlated-field updates being spread even wider. Reconsider if a
    # second producer appears — today detect_occurrences is the only one.
    occurrence_id: str
    workflow: str
    mode: OccurrenceMode
    parent_occurrence_id: str | None
    subject: dict[str, Any] | None
    invocation_source: str
    start_event: int
    started_at: str | None
    start_timestamp_source: str | None
    end_event: int | None = None
    finished_at: str | None = None
    finish_timestamp_source: str | None = None
    duration_ms: int | None = None
    boundary_confidence: BoundaryConfidence = "unknown"
    preceding_context_events: int = 0
    observed_models: list[str] = field(default_factory=list)
    observed_effort: list[str] = field(default_factory=list)
    model_effort_source: str | None = None
    model_effort_event_count: int = 0
    prompt_fingerprint: str | None = None


@dataclass(frozen=True)
class InventoryRow:
    workflow: str
    subject: dict[str, Any] | None
    session_id: str
    native_path: str
    cwd: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    longest_gap_ms: int | None
    event_count: int
    transcript_bytes: int
    observed_models: list[str] | None
    observed_effort: list[str] | None
    branch: str | None
    association_confidence: str
    manifest_status: str
    import_status: str


@dataclass(frozen=True)
class InventoryError:
    native_path: str
    error: str


@dataclass(frozen=True)
class InventoryResult:
    repository_root: str
    sessions: list[InventoryRow]
    errors: list[InventoryError]
    summary: dict[str, Any]


def load_registry(path: Path) -> dict[str, WorkflowDefinition]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"workflow registry is unreadable or malformed: {path}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("workflow registry requires schema_version 1")
    raw_workflows = document.get("workflows")
    if not isinstance(raw_workflows, dict) or not raw_workflows:
        raise ValueError("workflow registry requires a non-empty workflows object")

    definitions: dict[str, WorkflowDefinition] = {}
    aliases: set[str] = set()
    commands: set[str] = set()
    for workflow, raw in raw_workflows.items():
        if not isinstance(workflow, str) or not SAFE_ID.fullmatch(workflow) or not isinstance(raw, dict):
            raise ValueError("workflow ids must be safe strings with object definitions")
        user_commands = tuple(raw.get("user_commands", ()))
        skill_aliases = tuple(raw.get("skill_aliases", ()))
        if not user_commands or not skill_aliases or any(not isinstance(item, str) for item in user_commands + skill_aliases):
            raise ValueError(f"workflow {workflow!r} requires string command and Skill aliases")
        if commands.intersection(user_commands) or aliases.intersection(skill_aliases):
            raise ValueError(f"workflow {workflow!r} duplicates a command or Skill alias")
        commands.update(user_commands)
        aliases.update(skill_aliases)
        pattern_value = raw.get("argument_pattern")
        pattern = None
        if pattern_value is not None:
            if not isinstance(pattern_value, str):
                raise ValueError(f"workflow {workflow!r} argument_pattern must be a string or null")
            try:
                pattern = re.compile(pattern_value)
            except re.error as exc:
                raise ValueError(f"workflow {workflow!r} has an invalid argument_pattern") from exc
            if "number" not in pattern.groupindex:
                raise ValueError(f"workflow {workflow!r} numeric pattern requires a named number group")
        raw_surfaces = raw.get("surfaces", [])
        if not isinstance(raw_surfaces, list):
            raise ValueError(f"workflow {workflow!r} surfaces must be an array")
        surfaces = tuple(
            SurfaceDefinition(
                glob=item["glob"],
                load_class=item["load_class"],
                required=bool(item.get("required", False)),
            )
            for item in raw_surfaces
            if isinstance(item, dict)
            and isinstance(item.get("glob"), str)
            and isinstance(item.get("load_class"), str)
        )
        if len(surfaces) != len(raw_surfaces):
            raise ValueError(f"workflow {workflow!r} has an invalid surface definition")
        definitions[workflow] = WorkflowDefinition(
            workflow=workflow,
            user_commands=user_commands,
            skill_aliases=skill_aliases,
            subject_kind=str(raw.get("subject_kind", "unknown")),
            argument_pattern=pattern,
            allowed_parents=tuple(raw.get("allowed_parents", ())),
            surfaces=surfaces,
        )
    return definitions


def _timestamp_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.timestamp() * 1000)


def _utc_timestamp(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    value = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _content(record: dict[str, Any]) -> tuple[str, str | None, tuple[dict[str, Any], ...]]:
    message = record.get("message")
    role = message.get("role") if isinstance(message, dict) and isinstance(message.get("role"), str) else None
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    if isinstance(content, str):
        return content, role, ()
    texts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str):
                texts.append(item["text"])
            if item.get("type") == "tool_use":
                tool_uses.append(item)
    return "\n".join(texts), role, tuple(tool_uses)


def parse_events(raw: bytes) -> list[Event]:
    events: list[Event] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"transcript JSONL is malformed at line {line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"transcript JSONL record {line_number} is not an object")
        text, role, tool_uses = _content(record)
        timestamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        events.append(
            Event(
                index=len(events),
                raw=record,
                timestamp=timestamp,
                timestamp_ms=_timestamp_ms(timestamp),
                role=role,
                text=text,
                tool_uses=tool_uses,
            )
        )
    if not events:
        raise ValueError("transcript JSONL is empty")
    return events


def first_authoritative_user_event(events: list[Event]) -> Event | None:
    """Return the first effective user record that contains non-empty user text."""
    for event in events:
        authoritative_role = event.role or (
            event.raw.get("type") if isinstance(event.raw.get("type"), str) else None
        )
        if authoritative_role != "user":
            continue
        message = event.raw.get("message")
        content = message.get("content") if isinstance(message, dict) else event.raw.get("content")
        if isinstance(content, str) and content.strip():
            return event
        if isinstance(content, list) and any(
            isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
            and bool(item["text"].strip())
            for item in content
        ):
            return event
    return None


def _user_invocation(text: str, definitions: dict[str, WorkflowDefinition]) -> tuple[WorkflowDefinition, str] | None:
    markup = COMMAND_MARKUP.search(text)
    if markup:
        command = markup.group("command")
        command = command if command.startswith("/") else f"/{command}"
        args = markup.group("args").strip()
        for definition in definitions.values():
            if command in definition.user_commands:
                return definition, args
    for definition in definitions.values():
        for command in definition.user_commands:
            match = re.fullmatch(rf"{re.escape(command)}(?:\s+(?P<args>[\s\S]*))?", text.strip())
            if match:
                return definition, (match.group("args") or "").strip()
    return None


def _subject(definition: WorkflowDefinition, args: str) -> dict[str, Any] | None:
    if definition.subject_kind == "topic":
        return {"kind": "topic", "value": args} if args else {"kind": "topic", "value": None}
    if definition.argument_pattern is None:
        return None
    match = definition.argument_pattern.search(args)
    if not match:
        return {"kind": definition.subject_kind, "number": None}
    return {"kind": definition.subject_kind, "number": int(match.group("number"))}


def _skill_definition(tool_use: dict[str, Any], definitions: dict[str, WorkflowDefinition]) -> tuple[WorkflowDefinition, str] | None:
    if tool_use.get("name") != "Skill":
        return None
    inputs = tool_use.get("input")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("skill"), str):
        return None
    skill = inputs["skill"]
    args = inputs.get("args") if isinstance(inputs.get("args"), str) else ""
    for definition in definitions.values():
        if skill in definition.skill_aliases:
            return definition, args
    return None


def detect_occurrences(events: list[Event], definitions: dict[str, WorkflowDefinition]) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    counters: dict[str, int] = {}
    active_root_start: int | None = None

    def add(
        definition: WorkflowDefinition, event: Event, mode: OccurrenceMode, source: str, args: str
    ) -> None:
        counters[definition.workflow] = counters.get(definition.workflow, 0) + 1
        parent = None
        if mode == "nested":
            for candidate in reversed(occurrences):
                if (
                    active_root_start is not None
                    and candidate.start_event >= active_root_start
                    and candidate.workflow in definition.allowed_parents
                ):
                    parent = candidate.occurrence_id
                    break
        occurrences.append(
            Occurrence(
                occurrence_id=f"{definition.workflow}-{counters[definition.workflow]}",
                workflow=definition.workflow,
                mode=mode,
                parent_occurrence_id=parent,
                subject=_subject(definition, args),
                invocation_source=source,
                start_event=event.index,
                started_at=event.timestamp,
                start_timestamp_source="transcript_event" if event.timestamp else None,
                preceding_context_events=event.index,
            )
        )

    for event in events:
        authoritative_role = event.role or (event.raw.get("type") if isinstance(event.raw.get("type"), str) else None)
        if authoritative_role == "user":
            invocation = _user_invocation(event.text, definitions)
            if invocation:
                add(invocation[0], event, "top-level", "user_command", invocation[1])
                active_root_start = event.index
        if authoritative_role == "assistant":
            for tool_use in event.tool_uses:
                invocation = _skill_definition(tool_use, definitions)
                if invocation:
                    add(invocation[0], event, "nested", "assistant_skill_tool", invocation[1])
    return occurrences


def classify_inventory_occurrences(
    events: list[Event], definitions: dict[str, WorkflowDefinition]
) -> list[Occurrence]:
    """Classify only the workflow rooted in the first authoritative user message."""
    first_user = first_authoritative_user_event(events)
    if first_user is None:
        return []

    occurrences = detect_occurrences(events, definitions)
    direct = _user_invocation(first_user.text, definitions)
    if direct:
        expected_subject = _subject(direct[0], direct[1])
        return [
            occurrence
            for occurrence in occurrences
            if occurrence.mode == "top-level"
            and occurrence.start_event == first_user.index
            and occurrence.workflow == direct[0].workflow
            and occurrence.subject == expected_subject
        ][:1]

    command_matches: list[tuple[re.Match[str], WorkflowDefinition]] = []
    for definition in definitions.values():
        for command in definition.user_commands:
            pattern = rf"(?<![A-Za-z0-9:_-]){re.escape(command)}(?![A-Za-z0-9:_-])"
            command_matches.extend(
                (match, definition) for match in re.finditer(pattern, first_user.text)
            )
    if len(command_matches) != 1:
        return []

    command_match, definition = command_matches[0]
    embedded = _user_invocation(first_user.text[command_match.start() :], definitions)
    if embedded is None or embedded[0].workflow != definition.workflow:
        return []
    expected_subject = _subject(definition, embedded[1])
    for occurrence in occurrences:
        if (
            occurrence.mode == "nested"
            and occurrence.start_event > first_user.index
            and occurrence.workflow == definition.workflow
            and occurrence.subject == expected_subject
        ):
            occurrence.mode = "top-level"
            occurrence.parent_occurrence_id = None
            occurrence.invocation_source = "embedded_user_command_corroborated"
            occurrence.start_event = first_user.index
            occurrence.started_at = first_user.timestamp
            occurrence.start_timestamp_source = "transcript_event" if first_user.timestamp else None
            occurrence.preceding_context_events = first_user.index
            return [occurrence]
    return []


def _bundle_occurrences(
    events: list[Event],
    definitions: dict[str, WorkflowDefinition],
    admitted_root: Occurrence,
) -> list[Occurrence]:
    """Return every occurrence after first-message admission has selected the root."""
    occurrences = detect_occurrences(events, definitions)
    try:
        root = next(
            occurrence
            for occurrence in occurrences
            if occurrence.occurrence_id == admitted_root.occurrence_id
        )
    except StopIteration as exc:
        raise ValueError("admitted inventory root is missing from complete occurrences") from exc

    root.mode = admitted_root.mode
    root.parent_occurrence_id = admitted_root.parent_occurrence_id
    root.invocation_source = admitted_root.invocation_source
    root.start_event = admitted_root.start_event
    root.started_at = admitted_root.started_at
    root.start_timestamp_source = admitted_root.start_timestamp_source
    root.preceding_context_events = admitted_root.preceding_context_events
    if admitted_root.invocation_source != "embedded_user_command_corroborated":
        return occurrences

    occurrences.sort(key=lambda occurrence: occurrence.start_event)
    root_index = occurrences.index(root)
    active: list[Occurrence] = [root]
    for occurrence in occurrences[root_index + 1 :]:
        if occurrence.mode == "top-level":
            break
        allowed_parents = definitions[occurrence.workflow].allowed_parents
        occurrence.parent_occurrence_id = next(
            (
                candidate.occurrence_id
                for candidate in reversed(active)
                if candidate.workflow in allowed_parents
            ),
            None,
        )
        active.append(occurrence)
    return occurrences


def _completion_workflow(event: Event) -> str | None:
    marker = event.raw.get("workflow_completion")
    if isinstance(marker, str):
        return marker
    if isinstance(marker, dict) and isinstance(marker.get("workflow"), str):
        return marker["workflow"]
    return None


def resolve_boundaries(events: list[Event], occurrences: list[Occurrence]) -> None:
    """Normalize invocation times and attach only evidence-backed end boundaries."""
    by_id = {item.occurrence_id: item for item in occurrences}
    for occurrence in occurrences:
        start = events[occurrence.start_event]
        occurrence.started_at = _utc_timestamp(start.timestamp_ms)
        occurrence.start_timestamp_source = "transcript_event" if start.timestamp_ms is not None else None

        end: Event | None = None
        source: str | None = None
        confidence = "unknown"
        later_boundaries = [
            item for item in occurrences
            if item.start_event > occurrence.start_event
            and (item.mode == "top-level" or item.workflow == occurrence.workflow)
        ]
        next_boundary = min(later_boundaries, key=lambda item: item.start_event) if later_boundaries else None
        search_stop = next_boundary.start_event if next_boundary else len(events)
        for event in events[occurrence.start_event + 1 : search_stop]:
            if _completion_workflow(event) == occurrence.workflow:
                marker = event.raw.get("workflow_completion")
                if (
                    isinstance(marker, dict)
                    and marker.get("occurrence_id") is not None
                    and marker.get("occurrence_id") != occurrence.occurrence_id
                ):
                    continue
                end = event
                source = "explicit_completion_marker"
                confidence = "exact"
                break
            if occurrence.mode == "nested" and occurrence.parent_occurrence_id:
                parent = by_id.get(occurrence.parent_occurrence_id)
                continuation = event.raw.get("parent_continuation")
                if parent and continuation == parent.workflow:
                    end = event
                    source = "parent_continuation"
                    confidence = "approximate"
                    break

        if end is None and next_boundary and next_boundary.start_event - 1 > occurrence.start_event:
            end = events[next_boundary.start_event - 1]
            source = (
                "next_top_level_boundary"
                if next_boundary.mode == "top-level"
                else "next_same_workflow_boundary"
            )
            confidence = "approximate"
        if end is None and not next_boundary and events and events[-1].index > occurrence.start_event:
            end = events[-1]
            source = "terminal_stop_boundary"
            confidence = "approximate"
        boundary_end = end.index if end is not None else occurrence.start_event
        interval = events[occurrence.start_event : boundary_end + 1]
        models = {
            value for event in interval
            if isinstance((value := _record_value(event.raw, "model")), str) and value
        }
        efforts = {
            value for event in interval
            if isinstance((value := _record_value(event.raw, "effort")), str) and value
        }
        occurrence.observed_models = sorted(models)
        occurrence.observed_effort = sorted(efforts)
        occurrence.model_effort_event_count = sum(
            isinstance(_record_value(event.raw, "model"), str)
            or isinstance(_record_value(event.raw, "effort"), str)
            for event in interval
        )
        if occurrence.model_effort_event_count:
            occurrence.model_effort_source = "events_within_boundary"
        if end is None:
            continue
        occurrence.end_event = end.index
        occurrence.finished_at = _utc_timestamp(end.timestamp_ms)
        occurrence.finish_timestamp_source = source
        occurrence.boundary_confidence = confidence
        if start.timestamp_ms is not None and end.timestamp_ms is not None and end.timestamp_ms >= start.timestamp_ms:
            occurrence.duration_ms = end.timestamp_ms - start.timestamp_ms


def _message_content(record: dict[str, Any]) -> list[dict[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    return [item for item in content if isinstance(item, dict)] if isinstance(content, list) else []


def _record_value(record: dict[str, Any], key: str) -> Any:
    if key in record:
        return record[key]
    message = record.get("message")
    return message.get(key) if isinstance(message, dict) else None


def build_event_summary(events: list[Event], occurrences: list[Occurrence]) -> dict[str, Any]:
    """Build a compact privacy-safe index of mechanically observable facts."""
    event_counts: dict[str, int] = {}
    tool_by_name: dict[str, int] = {}
    tool_starts: dict[str, tuple[int, int | None, str]] = {}
    tool_shapes: dict[str, list[int]] = {}
    failed = denials = paired = 0
    dispatched = completed = waits = compactions = 0
    models: set[str] = set()
    efforts: set[str] = set()
    model_effort_events = 0
    usage_blocks: list[dict[str, int]] = []
    saw_usage = False
    evidence: list[dict[str, Any]] = []
    gaps: list[dict[str, int]] = []
    previous_timed: Event | None = None
    subagent_ids: set[str] = set()

    for event in events:
        event_type = event.raw.get("type") if isinstance(event.raw.get("type"), str) else "unknown"
        event_counts[f"type:{event_type}"] = event_counts.get(f"type:{event_type}", 0) + 1
        if event.role:
            event_counts[f"role:{event.role}"] = event_counts.get(f"role:{event.role}", 0) + 1

        if event.timestamp_ms is not None and previous_timed is not None:
            delta = event.timestamp_ms - previous_timed.timestamp_ms  # type: ignore[operator]
            if delta < 0:
                evidence.append({"kind": "decreasing_timestamp", "event_indexes": [previous_timed.index, event.index]})
            elif delta > 0:
                gaps.append({"duration_ms": delta, "start_event": previous_timed.index, "end_event": event.index})
        if event.timestamp_ms is not None:
            previous_timed = event

        model = _record_value(event.raw, "model")
        effort = _record_value(event.raw, "effort")
        if isinstance(model, str) and model:
            models.add(model)
        if isinstance(effort, str) and effort:
            efforts.add(effort)
        if isinstance(model, str) or isinstance(effort, str):
            model_effort_events += 1

        usage = _record_value(event.raw, "usage")
        if isinstance(usage, dict):
            saw_usage = True
            numeric = {key: value for key, value in usage.items() if isinstance(value, int) and not isinstance(value, bool)}
            if any(value > 0 for value in numeric.values()):
                usage_blocks.append(numeric)

        subtype = event.raw.get("subtype")
        if event_type in {"compact_boundary", "summary"} or subtype in {"compact_boundary", "context_summary"}:
            compactions += 1

        for tool in event.tool_uses:
            name = tool.get("name") if isinstance(tool.get("name"), str) else "unknown"
            tool_by_name[name] = tool_by_name.get(name, 0) + 1
            tool_id = tool.get("id")
            if isinstance(tool_id, str):
                tool_starts[tool_id] = (event.index, event.timestamp_ms, name)
            inputs = tool.get("input") if isinstance(tool.get("input"), dict) else {}
            shape = json.dumps({"name": name, "input": inputs}, sort_keys=True, separators=(",", ":"))
            tool_shapes.setdefault(shape, []).append(event.index)
            lowered = name.lower()
            if lowered in {"agent", "task"} or "spawn_agent" in lowered:
                dispatched += 1
                if isinstance(tool_id, str):
                    subagent_ids.add(tool_id)
            if "wait" in lowered:
                waits += 1

        for item in _message_content(event.raw):
            if item.get("type") != "tool_result":
                continue
            tool_id = item.get("tool_use_id")
            start = tool_starts.get(tool_id) if isinstance(tool_id, str) else None
            if start and start[1] is not None and event.timestamp_ms is not None and event.timestamp_ms >= start[1]:
                paired += 1
            is_error = item.get("is_error") is True
            if is_error:
                failed += 1
                content = item.get("content")
                error_text = content if isinstance(content, str) else ""
                if "permission denied" in error_text.lower() or "not allowed" in error_text.lower():
                    denials += 1
                    evidence.append({"kind": "permission_denial", "event_indexes": [event.index]})
            if isinstance(tool_id, str) and tool_id in subagent_ids:
                completed += 1

    retry_groups = [indexes for indexes in tool_shapes.values() if len(indexes) > 1]
    equivalent_retries = sum(len(indexes) - 1 for indexes in retry_groups)
    for indexes in retry_groups:
        evidence.append({"kind": "equivalent_tool_retry", "event_indexes": indexes})

    figures: dict[str, int] | None = None
    usage_shape = "unavailable"
    if usage_blocks:
        figures = {}
        for block in usage_blocks:
            for key, value in block.items():
                figures[key] = figures.get(key, 0) + value
        usage_shape = "real"
    elif saw_usage:
        usage_shape = "placeholder"

    sorted_gaps = sorted(gaps, key=lambda item: item["duration_ms"], reverse=True)
    workflow_invocations: dict[str, dict[str, int]] = {}
    for occurrence in occurrences:
        bucket = workflow_invocations.setdefault(occurrence.workflow, {"top-level": 0, "nested": 0})
        bucket[occurrence.mode] = bucket.get(occurrence.mode, 0) + 1

    return {
        "schema_version": 1,
        "timestamp_coverage": {"events": len(events), "with_timestamp": sum(item.timestamp_ms is not None for item in events)},
        "event_counts": dict(sorted(event_counts.items())),
        "tool_calls": {
            "by_name": dict(sorted(tool_by_name.items())),
            "failed": failed,
            "permission_denials": denials,
            "equivalent_retries": equivalent_retries,
            "paired_duration_count": paired,
        },
        "subagents": {"dispatched": dispatched, "completed": completed, "waits": waits},
        "compactions": {"count": compactions},
        "gaps": {"longest_ms": sorted_gaps[0]["duration_ms"] if sorted_gaps else None, "top": sorted_gaps[:5]},
        "usage": {"shape": usage_shape, "figures": figures},
        "model_effort": {
            "requested_model": None,
            "requested_model_source": None,
            "requested_effort": None,
            "requested_effort_source": None,
            "observed_models": sorted(models),
            "observed_effort": sorted(efforts),
            "coverage": model_effort_events,
        },
        "workflow_invocations": workflow_invocations,
        "evidence": evidence,
    }


def _observe_git(root: Path, *args: str) -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False, None
    return True, result.stdout.strip()


def _run_git(root: Path, *args: str) -> str | None:
    succeeded, output = _observe_git(root, *args)
    if not succeeded:
        return None
    return output or None


def _git_dirty_tree(root: Path) -> bool | None:
    succeeded, status = _observe_git(root, "status", "--porcelain")
    return bool(status) if succeeded else None


def _shared_storage_root(repository_root: Path) -> tuple[Path, str]:
    common_dir = _run_git(
        repository_root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    if common_dir:
        return Path(common_dir).resolve().parent, "git_common_dir_parent"
    return repository_root, "repository_root_fallback"


def _first_recorded_string(events: list[Event], *keys: str) -> str | None:
    for event in events:
        for key in keys:
            value = _record_value(event.raw, key)
            if isinstance(value, str) and value:
                return value
    return None


def _repository_association(
    native_path: Path,
    cwd: str | None,
    repository_root: Path,
) -> str | None:
    if cwd:
        cwd_path = Path(cwd).expanduser()
        if cwd_path.is_dir():
            resolved_cwd = cwd_path.resolve()
            if resolved_cwd == repository_root or repository_root in resolved_cwd.parents:
                return "exact"
            cwd_common = _run_git(
                resolved_cwd,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
            repository_common = _run_git(
                repository_root,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
            if (
                cwd_common
                and repository_common
                and Path(cwd_common).resolve() == Path(repository_common).resolve()
            ):
                return "exact"
            return None

    encoded_repository = str(repository_root).replace(os.sep, "-")
    if native_path.parent.name == encoded_repository:
        return "uncertain"
    return None


def _inventory_subject(subject: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep selectors useful without exposing free-form prompt arguments."""
    if not isinstance(subject, dict):
        return None
    kind = subject.get("kind")
    number = subject.get("number")
    if isinstance(kind, str) and isinstance(number, int) and not isinstance(number, bool):
        return {"kind": kind, "number": number}
    return {"kind": kind} if isinstance(kind, str) else None


def inventory_native_transcripts(
    projects_root: Path,
    repository_root: Path,
    registry_path: Path,
) -> InventoryResult:
    """Read native Claude JSONL one file at a time and return metadata-only rows."""
    projects_root = projects_root.expanduser()
    repository_root = repository_root.expanduser()
    if not projects_root.is_dir():
        raise ValueError(f"Claude projects root is unavailable: {projects_root}")
    if not repository_root.is_dir():
        raise ValueError(f"repository root is unavailable: {repository_root}")

    repository_root = repository_root.resolve()
    definitions = load_registry(registry_path)
    storage_root, _ = _shared_storage_root(repository_root)
    rows: list[InventoryRow] = []
    errors: list[InventoryError] = []
    scanned = readable = 0

    for native_path in sorted(projects_root.rglob("*.jsonl")):
        if not native_path.is_file():
            continue
        scanned += 1
        try:
            raw = native_path.read_bytes()
            events = parse_events(raw)
        except (OSError, ValueError) as exc:
            errors.append(
                InventoryError(
                    native_path=str(native_path.resolve()),
                    error=str(exc) or exc.__class__.__name__,
                )
            )
            continue
        readable += 1

        occurrences = classify_inventory_occurrences(events, definitions)
        if not occurrences:
            continue
        cwd = _first_recorded_string(events, "cwd")
        association_confidence = _repository_association(
            native_path,
            cwd,
            repository_root,
        )
        if association_confidence is None:
            continue

        timestamps = [event.timestamp_ms for event in events if event.timestamp_ms is not None]
        started_ms = min(timestamps) if timestamps else None
        finished_ms = max(timestamps) if timestamps else None
        summary = build_event_summary(events, occurrences)
        model_effort = summary["model_effort"]
        session_id = native_path.stem
        manifest = storage_root / ".prflow/tmp/workflow-manifests" / f"{session_id}.json"
        imported = storage_root / ".prflow/tmp/workflow-runs" / session_id / "transcript.jsonl"
        occurrence = occurrences[0]
        rows.append(
            InventoryRow(
                workflow=occurrence.workflow,
                subject=_inventory_subject(occurrence.subject),
                session_id=session_id,
                native_path=str(native_path.resolve()),
                cwd=str(Path(cwd).expanduser().resolve()) if cwd else None,
                started_at=_utc_timestamp(started_ms),
                finished_at=_utc_timestamp(finished_ms),
                duration_ms=(
                    finished_ms - started_ms
                    if len(timestamps) >= 2
                    and started_ms is not None
                    and finished_ms is not None
                    else None
                ),
                longest_gap_ms=summary["gaps"]["longest_ms"],
                event_count=len(events),
                transcript_bytes=len(raw),
                observed_models=model_effort["observed_models"] or None,
                observed_effort=model_effort["observed_effort"] or None,
                branch=_first_recorded_string(events, "gitBranch", "branch"),
                association_confidence=association_confidence,
                manifest_status="present" if manifest.is_file() else "absent",
                import_status="imported" if imported.is_file() else "not_imported",
            )
        )

    rows.sort(
        key=lambda row: (
            row.started_at is None,
            row.started_at or "",
            row.session_id,
            row.native_path,
        )
    )
    by_workflow: dict[str, int] = {}
    for row in rows:
        by_workflow[row.workflow] = by_workflow.get(row.workflow, 0) + 1
    summary = {
        "scanned": scanned,
        "readable": readable,
        "matched": len(rows),
        "already_bundled": sum(row.import_status == "imported" for row in rows),
        "unreadable": len(errors),
        "by_workflow": dict(sorted(by_workflow.items())),
    }
    return InventoryResult(
        repository_root=str(repository_root),
        sessions=rows,
        errors=errors,
        summary=summary,
    )


def inventory_document(result: InventoryResult) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repository_root": result.repository_root,
        "sessions": [asdict(row) for row in result.sessions],
        "errors": [asdict(error) for error in result.errors],
        "summary": result.summary,
    }


def render_inventory_json(result: InventoryResult) -> str:
    return json.dumps(inventory_document(result), indent=2, sort_keys=True) + "\n"


def render_inventory_table(result: InventoryResult) -> str:
    headings = (
        "WORKFLOW",
        "SUBJECT",
        "SESSION",
        "PATH",
        "CWD",
        "STARTED",
        "FINISHED",
        "DURATION_MS",
        "MAX_GAP_MS",
        "EVENTS",
        "BYTES",
        "MODEL",
        "EFFORT",
        "BRANCH",
        "ASSOCIATION",
        "MANIFEST",
        "IMPORT",
    )
    values: list[tuple[str, ...]] = []
    for row in result.sessions:
        values.append(
            (
                row.workflow,
                json.dumps(row.subject, sort_keys=True, separators=(",", ":")) if row.subject else "unavailable",
                row.session_id,
                row.native_path,
                row.cwd or "unavailable",
                row.started_at or "unavailable",
                row.finished_at or "unavailable",
                str(row.duration_ms) if row.duration_ms is not None else "unavailable",
                str(row.longest_gap_ms) if row.longest_gap_ms is not None else "unavailable",
                str(row.event_count),
                str(row.transcript_bytes),
                ",".join(row.observed_models or []) or "unavailable",
                ",".join(row.observed_effort or []) or "unavailable",
                row.branch or "unavailable",
                row.association_confidence,
                row.manifest_status,
                row.import_status,
            )
        )
    widths = [
        max(len(headings[index]), *(len(row[index]) for row in values))
        if values
        else len(headings[index])
        for index in range(len(headings))
    ]

    def format_row(row: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()

    lines = [format_row(headings), format_row(tuple("-" * width for width in widths))]
    lines.extend(format_row(row) for row in values)
    lines.append(
        "summary: "
        f"scanned={result.summary['scanned']} matched={result.summary['matched']} "
        f"already_bundled={result.summary['already_bundled']} unreadable={result.summary['unreadable']}"
    )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = handle.name
            handle.write(data)
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


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def measure_prompt_surfaces(
    root: Path,
    definitions: dict[str, WorkflowDefinition],
    occurrences: list[Occurrence],
) -> tuple[dict[str, Any], dict[str, str | None]]:
    active = {item.workflow for item in occurrences}
    surfaces: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    per_workflow: dict[str, list[dict[str, Any]]] = {workflow: [] for workflow in active}
    for workflow in sorted(active):
        for definition in definitions[workflow].surfaces:
            matches = sorted(path for path in root.glob(definition.glob) if path.is_file())
            if not matches:
                missing.append(
                    {
                        "workflow": workflow,
                        "glob": definition.glob,
                        "load_class": definition.load_class,
                        "required": definition.required,
                    }
                )
            for path in matches:
                data = path.read_bytes()
                relative = path.relative_to(root).as_posix()
                record = {
                    "path": relative,
                    "workflows": [workflow],
                    "load_class": definition.load_class,
                    "required": definition.required,
                    "bytes": len(data),
                    "lines": len(data.splitlines()),
                    "words": len(re.findall(r"\S+", data.decode("utf-8", errors="replace"))),
                    "approx_tokens": math.ceil(len(data) / 4),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                surfaces.append(record)
                per_workflow[workflow].append(record)

    fingerprints: dict[str, str | None] = {}
    for workflow, records in per_workflow.items():
        if not records:
            fingerprints[workflow] = None
            continue
        material = "".join(
            f"{item['path']}\0{item['sha256']}\0{item['load_class']}\n"
            for item in sorted(records, key=lambda value: (value["path"], value["load_class"]))
        ).encode()
        fingerprints[workflow] = hashlib.sha256(material).hexdigest()
    totals: dict[str, dict[str, int]] = {}
    totals_by_workflow: dict[str, dict[str, dict[str, int]]] = {}
    for surface in surfaces:
        bucket = totals.setdefault(surface["load_class"], {"bytes": 0, "lines": 0, "words": 0, "approx_tokens": 0})
        for key in bucket:
            bucket[key] += surface[key]
        for workflow in surface["workflows"]:
            workflow_bucket = totals_by_workflow.setdefault(workflow, {}).setdefault(
                surface["load_class"], {"bytes": 0, "lines": 0, "words": 0, "approx_tokens": 0}
            )
            for key in workflow_bucket:
                workflow_bucket[key] += surface[key]
    unique_by_path = {surface["path"]: surface for surface in surfaces}
    session_unique_totals = {"bytes": 0, "lines": 0, "words": 0, "approx_tokens": 0}
    for surface in unique_by_path.values():
        for key in session_unique_totals:
            session_unique_totals[key] += surface[key]
    return (
        {
            "schema_version": 1,
            "token_estimate": "ceil(bytes / 4); heuristic, not API-reported",
            "surfaces": surfaces,
            "totals_by_load_class": totals,
            "totals_note": "load-class totals are attribution totals and may include one physical path in multiple workflow contexts",
            "totals_by_workflow_load_class": totals_by_workflow,
            "session_unique_totals": session_unique_totals,
            "missing_surfaces": missing,
            "fingerprints": fingerprints,
        },
        fingerprints,
    )


CONFIG_KEYS = (
    "outputStyle",
    "verbose",
    "viewMode",
    "alwaysThinkingEnabled",
    "showThinkingSummaries",
)
CONFIG_ENV_KEYS = {
    "outputStyle": "DEVFLOW_RECORDER_OUTPUT_STYLE",
    "verbose": "DEVFLOW_RECORDER_VERBOSE",
    "viewMode": "DEVFLOW_RECORDER_VIEW_MODE",
    "alwaysThinkingEnabled": "DEVFLOW_RECORDER_ALWAYS_THINKING_ENABLED",
    "showThinkingSummaries": "DEVFLOW_RECORDER_SHOW_THINKING_SUMMARIES",
}


def _claude_configuration(root: Path) -> dict[str, Any]:
    candidates = [
        (Path.home() / ".claude/settings.json", "user_settings"),
        (root / ".claude/settings.json", "project_settings"),
        (root / ".claude/settings.local.json", "project_local_settings"),
    ]
    resolved: dict[str, dict[str, Any]] = {}
    for path, source in candidates:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        for key in CONFIG_KEYS:
            value = document.get(key)
            if isinstance(value, (str, bool, int, float)) or value is None and key in document:
                resolved[key] = {"value": value, "source": source, "effective": False}
    for key in CONFIG_KEYS:
        resolved.setdefault(key, {"value": None, "source": None, "effective": False})
        environment_value = os.environ.get(CONFIG_ENV_KEYS[key])
        if environment_value is not None:
            normalized: Any = environment_value
            if environment_value.lower() in {"true", "false"}:
                normalized = environment_value.lower() == "true"
            resolved[key] = {
                "value": normalized,
                "source": "explicit_recorder_environment",
                "effective": False,
                "declared_for_run": True,
            }
    return resolved


def _provider_classification() -> dict[str, Any]:
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return {"value": "bedrock", "source": "environment_marker"}
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        return {"value": "vertex", "source": "environment_marker"}
    if os.environ.get("CLAUDE_CODE_USE_FOUNDRY"):
        return {"value": "foundry", "source": "environment_marker"}
    if os.environ.get("ANTHROPIC_BASE_URL"):
        return {"value": "custom_base_url", "source": "environment_marker"}
    return {"value": None, "source": None}


def _prompt_candidate(
    prompt: str,
    definitions: dict[str, WorkflowDefinition],
) -> tuple[WorkflowDefinition, str, str] | None:
    """Return one provisional command candidate without retaining prompt prose."""
    markup = COMMAND_MARKUP.search(prompt)
    if markup:
        invocation = _user_invocation(prompt, definitions)
        if invocation is None:
            return None
        return invocation[0], invocation[1], "command_markup"

    direct = _user_invocation(prompt, definitions)
    if direct:
        return direct[0], direct[1], "exact_user_command"

    matches: list[tuple[re.Match[str], WorkflowDefinition]] = []
    for definition in definitions.values():
        for command in definition.user_commands:
            pattern = rf"(?<![A-Za-z0-9:_-]){re.escape(command)}(?![A-Za-z0-9:_-])"
            matches.extend((match, definition) for match in re.finditer(pattern, prompt))
    if len(matches) != 1:
        return None
    match, definition = matches[0]
    invocation = _user_invocation(prompt[match.start() :], definitions)
    if invocation is None or invocation[0].workflow != definition.workflow:
        return None
    return definition, invocation[1], "embedded_user_command_candidate"


def _plugin_version(root: Path) -> dict[str, Any]:
    try:
        document = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"value": None, "source": None}
    version = document.get("version") if isinstance(document, dict) else None
    if not isinstance(version, str) or not version:
        return {"value": None, "source": None}
    return {"value": version, "source": "plugin_manifest"}


def capture_prompt_manifest(payload: dict[str, Any], registry_path: Path) -> dict[str, Any]:
    """Capture start metadata for one provisional workflow without reading its transcript."""
    if not isinstance(payload, dict):
        raise ValueError("UserPromptSubmit payload must be a JSON object")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SAFE_ID.fullmatch(session_id):
        raise ValueError("session_id is missing or unsafe")
    transcript_path = payload.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        raise ValueError("transcript_path is missing")
    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str) or not Path(cwd_value).is_dir():
        raise ValueError("cwd is missing or is not an existing directory")
    prompt = payload.get("user_prompt") if "user_prompt" in payload else payload.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("user_prompt or prompt is missing")

    definitions = load_registry(registry_path)
    candidate = _prompt_candidate(prompt, definitions)
    if candidate is None:
        return {"captured": False, "session_id": session_id}
    definition, args, invocation_evidence = candidate

    cwd = Path(cwd_value).resolve()
    git_root = _run_git(cwd, "rev-parse", "--show-toplevel")
    root = Path(git_root).resolve() if git_root else cwd
    storage_root, storage_root_source = _shared_storage_root(root)
    head_sha = _run_git(root, "rev-parse", "HEAD")
    branch = _run_git(root, "branch", "--show-current")
    dirty_tree = _git_dirty_tree(root)

    occurrence = Occurrence(
        occurrence_id=f"{definition.workflow}-provisional",
        workflow=definition.workflow,
        mode="top-level",
        parent_occurrence_id=None,
        subject=_subject(definition, args),
        invocation_source=invocation_evidence,
        start_event=0,
        started_at=None,
        start_timestamp_source=None,
    )
    prompt_surfaces, _ = measure_prompt_surfaces(root, definitions, [occurrence])
    requested_model = payload.get("model")
    requested_effort = payload.get("effort")
    if not isinstance(requested_model, str) or not requested_model:
        requested_model = None
    if not isinstance(requested_effort, str) or not requested_effort:
        requested_effort = None
    requested_model_source = "user_prompt_submit_payload" if requested_model else None
    requested_effort_source = "user_prompt_submit_payload" if requested_effort else None
    # A launch-line DEVFLOW_RECORDER_MODEL/EFFORT declaration is provenance, not an
    # observation, so it only fills what the payload did not already observe.
    if not requested_model:
        declared_model = os.environ.get("DEVFLOW_RECORDER_MODEL")
        if declared_model:
            requested_model = declared_model
            requested_model_source = "explicit_recorder_environment"
    if not requested_effort:
        declared_effort = os.environ.get("DEVFLOW_RECORDER_EFFORT")
        if declared_effort:
            requested_effort = declared_effort
            requested_effort_source = "explicit_recorder_environment"
    claude_code_version = payload.get("claude_code_version")
    version_source = "user_prompt_submit_payload"
    if not isinstance(claude_code_version, str) or not claude_code_version:
        claude_code_version = os.environ.get("CLAUDE_CODE_VERSION") or None
        version_source = "environment" if claude_code_version else None

    manifest = {
        "schema_version": 1,
        "session_id": session_id,
        "native_transcript_path": transcript_path,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "cwd": str(cwd),
        "candidate": {
            "workflow": definition.workflow,
            "subject": _inventory_subject(_subject(definition, args)),
            "invocation_evidence": invocation_evidence,
            "provisional": True,
        },
        "repository_root": str(root),
        "storage_root": str(storage_root),
        "storage_root_source": storage_root_source,
        "git": {"head_sha": head_sha, "branch": branch, "dirty_tree": dirty_tree},
        "prflow_version": _plugin_version(root),
        "claude_configuration": _claude_configuration(root),
        "claude_code_version": {"value": claude_code_version, "source": version_source},
        "provider": _provider_classification(),
        "model_effort": {
            "requested_model": requested_model,
            "requested_model_source": requested_model_source,
            "requested_effort": requested_effort,
            "requested_effort_source": requested_effort_source,
        },
        "prompt_surfaces": prompt_surfaces,
        "warnings": ["embedded command candidates require native transcript corroboration"]
        if invocation_evidence == "embedded_user_command_candidate"
        else [],
    }
    path = storage_root / ".prflow/tmp/workflow-manifests" / f"{session_id}.json"
    _atomic_write(path, _json_bytes(manifest))
    return {"captured": True, "session_id": session_id, "manifest": str(path)}


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    finally:
        os.close(descriptor)


def _read_start_manifest(path: Path, session_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"start manifest is unreadable or malformed: {path}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError(f"start manifest requires schema_version 1: {path}")
    if document.get("session_id") != session_id:
        raise ValueError(f"start manifest session_id does not match {session_id!r}")
    return document


def _write_session_bundle(
    session_id: str,
    raw: bytes,
    occurrences: list[Occurrence],
    repository_root: Path,
    storage_root: Path,
    storage_root_source: str,
    definitions: dict[str, WorkflowDefinition],
    start_manifest: dict[str, Any] | None,
    *,
    source: str,
    claude_code_version: Any = None,
) -> tuple[Path, str, int]:
    """Write one analysis bundle from already-selected native transcript bytes."""
    events = parse_events(raw)
    resolve_boundaries(events, occurrences)

    if start_manifest is not None:
        prompt_surfaces = start_manifest.get("prompt_surfaces")
        if not isinstance(prompt_surfaces, dict):
            raise ValueError("start manifest is missing prompt_surfaces")
        fingerprints = prompt_surfaces.get("fingerprints")
        if not isinstance(fingerprints, dict):
            raise ValueError("start manifest prompt_surfaces is missing fingerprints")
    else:
        prompt_surfaces, fingerprints = measure_prompt_surfaces(
            repository_root,
            definitions,
            occurrences,
        )
    # A start manifest is captured at UserPromptSubmit, when only the root occurrence
    # exists, so it fingerprints that workflow's surfaces alone. Occurrences of any other
    # workflow (nested dispatches) therefore keep a None fingerprint here, which makes
    # them recurrence-ineligible: deliberate, because the only fingerprint we could give
    # them is a Stop-time measurement of a surface that was never the launch-time one.
    for occurrence in occurrences:
        fingerprint = fingerprints.get(occurrence.workflow)
        occurrence.prompt_fingerprint = fingerprint if isinstance(fingerprint, str) else None

    summary = build_event_summary(events, occurrences)
    if start_manifest is not None:
        requested = start_manifest.get("model_effort")
        if isinstance(requested, dict):
            for key in (
                "requested_model",
                "requested_model_source",
                "requested_effort",
                "requested_effort_source",
            ):
                summary["model_effort"][key] = requested.get(key)
    else:
        declared_model = os.environ.get("DEVFLOW_RECORDER_MODEL")
        declared_effort = os.environ.get("DEVFLOW_RECORDER_EFFORT")
        if declared_model:
            summary["model_effort"]["requested_model"] = declared_model
            summary["model_effort"]["requested_model_source"] = "explicit_recorder_environment"
        if declared_effort:
            summary["model_effort"]["requested_effort"] = declared_effort
            summary["model_effort"]["requested_effort_source"] = "explicit_recorder_environment"

    if start_manifest is not None:
        git = start_manifest.get("git")
        git = git if isinstance(git, dict) else {}
        branch = git.get("branch")
        head_sha = git.get("head_sha")
        dirty_tree = git.get("dirty_tree")
        claude_configuration = start_manifest.get("claude_configuration")
        if not isinstance(claude_configuration, dict):
            claude_configuration = _claude_configuration(repository_root)
        recorded_version = start_manifest.get("claude_code_version")
        if not isinstance(recorded_version, dict):
            recorded_version = {"value": None, "source": None}
        provider = start_manifest.get("provider")
        if not isinstance(provider, dict):
            provider = _provider_classification()
        manifest_warnings = start_manifest.get("warnings")
        warnings = [
            warning
            for warning in manifest_warnings
            if isinstance(warning, str)
        ] if isinstance(manifest_warnings, list) else []
        metadata_repository_root = start_manifest.get("repository_root")
        if not isinstance(metadata_repository_root, str) or not metadata_repository_root:
            metadata_repository_root = str(repository_root)
    else:
        branch = _run_git(repository_root, "branch", "--show-current")
        head_sha = _run_git(repository_root, "rev-parse", "HEAD")
        dirty_tree = _git_dirty_tree(repository_root)
        claude_configuration = _claude_configuration(repository_root)
        recorded_version = {
            "value": claude_code_version or os.environ.get("CLAUDE_CODE_VERSION"),
            "source": (
                "stop_payload"
                if claude_code_version
                else ("environment" if os.environ.get("CLAUDE_CODE_VERSION") else None)
            ),
        }
        provider = _provider_classification()
        warnings = []
        metadata_repository_root = str(repository_root)
        if source == "explicit_import":
            warnings.append(
                "start manifest unavailable; prompt/config/git metadata measured at import time"
            )
    warnings.append("file-derived Claude settings may be overridden by CLI or managed settings")

    captured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    timed = [event.timestamp_ms for event in events if event.timestamp_ms is not None]
    metadata = {
        "schema_version": 2,
        "session_id": session_id,
        "captured_at": captured_at,
        "repository_root": metadata_repository_root,
        "storage_root": str(storage_root),
        "storage_root_source": storage_root_source,
        "branch": branch,
        "head_sha": head_sha,
        "dirty_tree": dirty_tree,
        "transcript_bytes": len(raw),
        "event_count": len(events),
        "occurrence_count": len(occurrences),
        "session_started_at": _utc_timestamp(min(timed)) if timed else None,
        "session_finished_at": _utc_timestamp(max(timed)) if timed else None,
        "claude_configuration": claude_configuration,
        "claude_code_version": recorded_version,
        "provider": provider,
        "warnings": warnings,
    }
    bundle = storage_root / ".prflow/tmp/workflow-runs" / session_id
    bundle.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(bundle, 0o700)
    _atomic_write(bundle / "transcript.jsonl", raw)
    _atomic_write(bundle / "metadata.json", _json_bytes(metadata))
    _atomic_write(bundle / "occurrences.json", _json_bytes([asdict(item) for item in occurrences]))
    _atomic_write(bundle / "prompt-surfaces.json", _json_bytes(prompt_surfaces))
    _atomic_write(bundle / "event-summary.json", _json_bytes(summary))
    return bundle, captured_at, len(events)


def _append_bundle_attempt(
    bundle: Path,
    captured_at: str,
    raw: bytes,
    event_count: int,
    source: str,
) -> None:
    _append_jsonl(
        bundle / "stop-attempts.jsonl",
        {
            "captured_at": captured_at,
            "transcript_bytes": len(raw),
            "transcript_sha256": hashlib.sha256(raw).hexdigest(),
            "event_count": event_count,
            "result": "captured",
            "source": source,
        },
    )


def import_inventory_session(
    session_id: str,
    projects_root: Path,
    repository_root: Path,
    registry_path: Path,
) -> Path:
    """Explicitly import exactly one inventoried native session by ID."""
    if not isinstance(session_id, str) or not SAFE_ID.fullmatch(session_id):
        raise ValueError("session_id is missing or unsafe")
    inventory = inventory_native_transcripts(projects_root, repository_root, registry_path)
    matches = [row for row in inventory.sessions if row.session_id == session_id]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one inventoried session for {session_id!r}; found {len(matches)}"
        )

    repository_root = repository_root.expanduser().resolve()
    storage_root, storage_root_source = _shared_storage_root(repository_root)
    native_path = Path(matches[0].native_path)
    try:
        raw = native_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"selected native transcript is unreadable: {native_path}") from exc
    definitions = load_registry(registry_path)
    events = parse_events(raw)
    admission = classify_inventory_occurrences(events, definitions)
    if not admission:
        raise ValueError("selected native transcript no longer classifies as an inventory session")
    occurrences = _bundle_occurrences(events, definitions, admission[0])
    manifest_path = storage_root / ".prflow/tmp/workflow-manifests" / f"{session_id}.json"
    start_manifest = _read_start_manifest(manifest_path, session_id)

    bundle, captured_at, event_count = _write_session_bundle(
        session_id,
        raw,
        occurrences,
        repository_root,
        storage_root,
        storage_root_source,
        definitions,
        start_manifest,
        source="explicit_import",
    )
    destination = bundle / "transcript.jsonl"
    destination_bytes = destination.read_bytes()
    source_hash = hashlib.sha256(raw).digest()
    if destination_bytes != raw or hashlib.sha256(destination_bytes).digest() != source_hash:
        raise OSError(f"imported transcript verification failed: {destination}")
    _append_bundle_attempt(bundle, captured_at, raw, event_count, "explicit_import")
    return bundle


def capture_stop_payload(payload: dict[str, Any], registry_path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Stop payload must be a JSON object")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SAFE_ID.fullmatch(session_id):
        raise ValueError("session_id is missing or unsafe")
    transcript_value = payload.get("transcript_path")
    if not isinstance(transcript_value, str) or not transcript_value:
        raise ValueError("transcript_path is missing")
    transcript_path = Path(transcript_value)
    if not transcript_path.is_file() or not os.access(transcript_path, os.R_OK):
        raise ValueError("transcript_path is not a readable regular file")
    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str) or not Path(cwd_value).is_dir():
        raise ValueError("cwd is missing or is not an existing directory")
    cwd = Path(cwd_value).resolve()
    git_root = _run_git(cwd, "rev-parse", "--show-toplevel")
    root = Path(git_root).resolve() if git_root else cwd
    storage_root, storage_root_source = _shared_storage_root(root)

    raw = transcript_path.read_bytes()
    events = parse_events(raw)
    definitions = load_registry(registry_path)
    occurrences = detect_occurrences(events, definitions)
    if not occurrences:
        return {"captured": False, "session_id": session_id}
    bundle, captured_at, event_count = _write_session_bundle(
        session_id,
        raw,
        occurrences,
        root,
        storage_root,
        storage_root_source,
        definitions,
        None,
        source="stop_observer",
        claude_code_version=payload.get("claude_code_version"),
    )
    _append_bundle_attempt(bundle, captured_at, raw, event_count, "stop_observer")
    return {"captured": True, "session_id": session_id, "bundle": str(bundle)}


def fail_open_main(registry_path: Path, stream: Any = sys.stdin) -> int:
    try:
        payload = json.load(stream)
        capture_stop_payload(payload, registry_path)
    except Exception as exc:  # Stop observers must never block the session they observe.
        print(
            f"devflow: implement-flight-recorder: workflow-flight-recorder: {str(exc) or exc.__class__.__name__}",
            file=sys.stderr,
        )
    return 0


def fail_open_manifest_main(registry_path: Path, stream: Any = sys.stdin) -> int:
    try:
        payload = json.load(stream)
        capture_prompt_manifest(payload, registry_path)
    except Exception as exc:  # UserPromptSubmit observers must never block the prompt.
        print(
            f"devflow: workflow-manifest-observer: {str(exc) or exc.__class__.__name__}",
            file=sys.stderr,
        )
    return 0
